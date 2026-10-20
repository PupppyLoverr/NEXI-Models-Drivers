//! The NEXI-CUA-1 network (`nexi_cua/policy/model.py`), run with tract.
//!
//! The asset is one ONNX file (`scripts/export_onnx.py` writes it from
//! nexi-cua's `nexi-cua-1.pt`). Weights are stored as fp32 (or as fp16 with
//! `--fp16`, which does not pass the gate) and computed in fp32. The graph
//! starts after `text_proj`, the 12288 -> 80 projection of the hashed text
//! features: its weight rides in the same file as an initializer the graph
//! does not use, and is applied here to the non-zero buckets only. That is the same linear map as nexi's dense `nn.Linear`,
//! without a 512 x 12288 dense input (25 MB per decision).

use crate::features::{SparseText, NUMERIC_DIM, TEXT_DIM};
use crate::infer::Calibration;
use anyhow::{anyhow, bail, Context};
use std::path::Path;
use tract_onnx::pb::{tensor_proto::DataType, TensorProto};
use tract_onnx::prelude::*;

pub const TEXT_PROJ: usize = 80;
const TEXT_WEIGHT: &str = "text_proj.weight";
const TEXT_BIAS: &str = "text_proj.bias";

/// Model inputs for one decision (`SemanticPolicy._batch`, unpadded).
#[derive(Clone, Debug, Default)]
pub struct Batch {
    pub goal_text: SparseText,
    pub role_idx: Vec<i64>,
    pub elem_text: Vec<SparseText>,
    pub numeric: Vec<[f32; NUMERIC_DIM]>,
    pub verb_idx: Vec<i64>,
    /// Index into the batch's elements, or -1 for no target.
    pub tgt_idx: Vec<i64>,
    pub arg_text: Vec<SparseText>,
}

/// A loaded NEXI-CUA-1.
pub struct Model {
    pub calibration: Calibration,
    plan: std::sync::Arc<TypedRunnableModel>,
    /// `text_proj.weight` transposed to `[bucket][80]`.
    text_weight: Vec<f32>,
    text_bias: [f32; TEXT_PROJ],
}

impl Model {
    pub fn load(path: &Path) -> TractResult<Self> {
        let onnx = tract_onnx::onnx();
        let mut file =
            std::fs::File::open(path).with_context(|| format!("opening {}", path.display()))?;
        let mut proto = onnx.proto_model_for_read(&mut file)?;
        let metadata = |key: &str| -> TractResult<f64> {
            proto
                .metadata_props
                .iter()
                .find(|entry| entry.key == key)
                .ok_or_else(|| anyhow!("the model file has no {key}"))?
                .value
                .parse::<f64>()
                .with_context(|| format!("reading {key}"))
        };
        // nexi-cua-1.calib.json, carried in the file.
        let calibration = Calibration {
            temperature: metadata("temperature")?,
            abstain_threshold: metadata("abstain_threshold")?,
        };
        let graph = proto
            .graph
            .as_mut()
            .ok_or_else(|| anyhow!("the model file has no graph"))?;
        // Inside a block so the proto's copies and the untransposed weight
        // are freed before tract builds its own model.
        let (text_weight, text_bias) = {
            let weight = take_initializer(&mut graph.initializer, TEXT_WEIGHT)?;
            let bias = take_initializer(&mut graph.initializer, TEXT_BIAS)?;
            let weight = weights_f32(&weight, &[TEXT_PROJ, TEXT_DIM])?;
            let bias = weights_f32(&bias, &[TEXT_PROJ])?;
            // [80][12288] -> [12288][80], so one bucket is one contiguous row.
            let mut text_weight = vec![0f32; TEXT_DIM * TEXT_PROJ];
            for out in 0..TEXT_PROJ {
                for bucket in 0..TEXT_DIM {
                    text_weight[bucket * TEXT_PROJ + out] = weight[out * TEXT_DIM + bucket];
                }
            }
            let mut text_bias = [0f32; TEXT_PROJ];
            text_bias.copy_from_slice(&bias);
            (text_weight, text_bias)
        };
        let plan = onnx
            .model_for_proto_model(&proto)?
            .into_optimized()?
            .into_runnable()?;
        drop(proto);
        release_free_memory();
        Ok(Self {
            calibration,
            plan,
            text_weight,
            text_bias,
        })
    }

    /// `text_proj(text_features(...))` for one sparse vector.
    fn project(&self, text: &SparseText, out: &mut [f32]) {
        out.copy_from_slice(&self.text_bias);
        // nn.Linear adds the bias after the product; the sum is reordered
        // either way, so add the terms to the bias directly.
        let mut acc = [0f32; TEXT_PROJ];
        for &(bucket, value) in text {
            let row = &self.text_weight[bucket as usize * TEXT_PROJ..][..TEXT_PROJ];
            for (slot, w) in acc.iter_mut().zip(row) {
                *slot += w * value;
            }
        }
        for (slot, sum) in out.iter_mut().zip(acc) {
            *slot += sum;
        }
    }

    fn project_rows(&self, rows: &[SparseText]) -> TractResult<Tensor> {
        let mut data = vec![0f32; rows.len() * TEXT_PROJ];
        for (row, out) in rows.iter().zip(data.chunks_mut(TEXT_PROJ)) {
            self.project(row, out);
        }
        Ok(Tensor::from_shape(&[rows.len(), TEXT_PROJ], &data)?)
    }

    /// Run the network: `(logits, correctness logits)`, one per candidate.
    pub fn run(&self, batch: &Batch) -> TractResult<(Vec<f32>, Vec<f32>)> {
        let m = batch.verb_idx.len();
        if m == 0 {
            return Ok((Vec::new(), Vec::new()));
        }
        // nexi pads to 512 masked elements. With no real element every row
        // the attention sees is that padding row, so feed one of it.
        let pad;
        let (role_idx, elem_text, numeric) = if batch.role_idx.is_empty() {
            pad = (
                vec![0i64],
                vec![SparseText::new()],
                vec![[0f32; NUMERIC_DIM]],
            );
            (&pad.0, &pad.1, &pad.2)
        } else {
            (&batch.role_idx, &batch.elem_text, &batch.numeric)
        };
        let k = role_idx.len();
        let numeric_flat: Vec<f32> = numeric.iter().flatten().copied().collect();
        let inputs: TVec<TValue> = tvec![
            self.project_rows(std::slice::from_ref(&batch.goal_text))?
                .into(),
            self.project_rows(elem_text)?.into(),
            Tensor::from_shape(&[k], role_idx)?.into(),
            Tensor::from_shape(&[k, NUMERIC_DIM], &numeric_flat)?.into(),
            Tensor::from_shape(&[m], &batch.verb_idx)?.into(),
            Tensor::from_shape(&[m], &batch.tgt_idx)?.into(),
            self.project_rows(&batch.arg_text)?.into(),
        ];
        let outputs = self.plan.run(inputs)?;
        let logits = outputs[0]
            .to_plain_array_view::<f32>()?
            .iter()
            .copied()
            .collect();
        let corr = outputs[1]
            .to_plain_array_view::<f32>()?
            .iter()
            .copied()
            .collect();
        Ok((logits, corr))
    }
}

/// Hand the allocator's free pages back to the OS. Loading builds several
/// transient copies of the weights on whichever thread loads; glibc keeps
/// such freed memory resident in that thread's arena unless asked.
pub fn release_free_memory() {
    #[cfg(all(target_os = "linux", target_env = "gnu"))]
    // SAFETY: malloc_trim only returns free heap pages to the kernel.
    unsafe {
        libc::malloc_trim(0);
    }
}

fn take_initializer(list: &mut Vec<TensorProto>, name: &str) -> TractResult<TensorProto> {
    let at = list
        .iter()
        .position(|t| t.name == name)
        .ok_or_else(|| anyhow!("the model file has no {name}"))?;
    Ok(list.remove(at))
}

/// An fp16 initializer (the shipped asset) widened to fp32. fp32 is also
/// read, for comparing against an unrounded export.
fn weights_f32(tensor: &TensorProto, shape: &[usize]) -> TractResult<Vec<f32>> {
    let dims: Vec<usize> = tensor.dims.iter().map(|d| *d as usize).collect();
    if dims != shape {
        bail!("{} has shape {dims:?}, expected {shape:?}", tensor.name);
    }
    let count: usize = shape.iter().product();
    if tensor.data_type == DataType::Float16 as i32 {
        if tensor.raw_data.len() == count * 2 {
            return Ok(tensor
                .raw_data
                .chunks_exact(2)
                .map(|b| f16::from_bits(u16::from_le_bytes([b[0], b[1]])).to_f32())
                .collect());
        }
        // Without raw_data, ONNX keeps fp16 bit patterns in int32_data.
        if tensor.int32_data.len() == count {
            return Ok(tensor
                .int32_data
                .iter()
                .map(|v| f16::from_bits(*v as u16).to_f32())
                .collect());
        }
    } else if tensor.data_type == DataType::Float as i32 {
        if tensor.raw_data.len() == count * 4 {
            return Ok(tensor
                .raw_data
                .chunks_exact(4)
                .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
                .collect());
        }
        if tensor.float_data.len() == count {
            return Ok(tensor.float_data.clone());
        }
    }
    bail!("{} holds no fp16 or fp32 data", tensor.name)
}
