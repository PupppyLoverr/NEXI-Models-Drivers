//! Dove W1: tree-first, screenshot-optional observation for `get_window_state`.
//!
//! * The screenshot policy: a read returns a screenshot only when the caller
//!   asks for one (`include_screenshot:true`, `marks:true`,
//!   `screenshot_out_file`, a screenshot-only read), when the session was
//!   started with `start_session {vision:true}`, or when the accessibility
//!   tree is empty or too sparse to act on (canvas, games, remote desktop).
//! * The per-session `vision` flag behind that policy.
//! * The image handed to the model: JPEG unless `screenshot_format:"png"`,
//!   optionally with set-of-marks labels (`marks:true`) that draw each row's
//!   index `N` at its element frame, so a vision model acts by element_token
//!   `<snapshot_id>:N` instead of by pixel.
//!
//! The capture registered for pixel actions stays the clean PNG; only the
//! copy embedded in the response is marked and re-encoded.

use anyhow::Result;
use image::{DynamicImage, ImageFormat, Rgba, RgbaImage};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::sync::{Mutex, Once, OnceLock};

/// A tree with fewer actionable elements than this is treated as a surface
/// the tree cannot describe (a canvas or game window only exposes its title
/// bar buttons), so the read includes a screenshot.
pub const SPARSE_TREE_ELEMENTS: usize = 5;

/// JPEG quality for model-facing screenshots.
pub const JPEG_QUALITY: u8 = 80;

/// At most this many marks are drawn on one screenshot.
const MAX_MARKS: usize = 400;

/// Schema fragments for the `get_window_state` inputs this module reads.
pub fn window_state_schema_properties() -> Value {
    json!({
        "marks": {
            "type": "boolean",
            "description": "Default false. Return a screenshot with set-of-marks labels: each element row's index N is drawn at its frame, so you can act by element_token <snapshot_id>:N on what you see. Implies a screenshot."
        },
        "screenshot_format": {
            "type": "string",
            "enum": ["jpeg", "png"],
            "description": "Encoding of the embedded screenshot. Default \"jpeg\" (smaller); \"png\" is lossless. screenshot_out_file always writes PNG."
        }
    })
}

/// Add `marks` and `screenshot_format` to a backend's `get_window_state`
/// input schema.
pub fn extend_window_state_schema(mut schema: Value) -> Value {
    if let (Some(props), Some(extra)) = (
        schema.get_mut("properties").and_then(Value::as_object_mut),
        window_state_schema_properties().as_object().cloned(),
    ) {
        props.extend(extra);
    }
    schema
}

/// Schema fragment for `start_session.vision`.
pub fn start_session_vision_schema() -> Value {
    json!({
        "type": "boolean",
        "description": "Default false. Declare a vision session: every get_window_state read in it returns a screenshot unless it passes include_screenshot:false. Without it, reads are tree-first and include a screenshot only when asked for or when the tree is empty or sparse."
    })
}

/// Add `vision` to the `start_session` input schema.
pub fn extend_start_session_schema(mut schema: Value) -> Value {
    if let Some(props) = schema.get_mut("properties").and_then(Value::as_object_mut) {
        props.insert("vision".into(), start_session_vision_schema());
    }
    schema
}

// ── per-session vision flag ───────────────────────────────────────────────

/// The session a call belongs to: its (runtime-namespaced) `session` label,
/// else the transport's implicit `_session_id`. Same order as
/// `start_session` uses, so a flag set there is found by later reads.
pub fn session_key(args: &Value) -> Option<String> {
    let args = args.as_object()?;
    ["session", "_session_id"].into_iter().find_map(|key| {
        args.get(key)
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty() && *s != "default")
            .map(str::to_owned)
    })
}

fn vision_sessions() -> &'static Mutex<HashSet<String>> {
    static SET: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();
    SET.get_or_init(|| Mutex::new(HashSet::new()))
}

/// Record `start_session {vision}` for the call's session. `vision:false`
/// clears an earlier `true`; omitting it leaves the flag as it was.
pub fn record_start_session(args: &Value) {
    let Some(vision) = args.get("vision").and_then(Value::as_bool) else {
        return;
    };
    let Some(key) = session_key(args) else {
        return;
    };
    static CLEAR_ON_END: Once = Once::new();
    CLEAR_ON_END.call_once(|| {
        crate::session::register_session_end_hook(|session| {
            vision_sessions()
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .remove(session);
        });
    });
    let mut set = vision_sessions().lock().unwrap_or_else(|e| e.into_inner());
    if vision {
        set.insert(key);
    } else {
        set.remove(&key);
    }
}

/// Whether the call's session was started with `vision:true`.
pub fn session_vision(args: &Value) -> bool {
    session_key(args).is_some_and(|key| {
        vision_sessions()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .contains(&key)
    })
}

// ── screenshot policy ─────────────────────────────────────────────────────

/// Why a read carries a screenshot.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ShotReason {
    /// `include_screenshot:true` or `screenshot_out_file`.
    Requested,
    /// `marks:true`.
    Marks,
    /// The session declared `vision:true`.
    Vision,
    /// `include_accessibility_tree:false`: the screenshot is the whole read.
    NoTree,
    /// The tree walk found fewer than [`SPARSE_TREE_ELEMENTS`] elements.
    SparseTree,
}

impl ShotReason {
    pub fn as_str(self) -> &'static str {
        match self {
            ShotReason::Requested => "requested",
            ShotReason::Marks => "marks",
            ShotReason::Vision => "vision_session",
            ShotReason::NoTree => "no_tree",
            ShotReason::SparseTree => "sparse_tree",
        }
    }
}

/// The screenshot decision as far as the arguments settle it, before the
/// tree walk.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ShotPolicy {
    Always(ShotReason),
    Never,
    /// Decided by the walked tree: a screenshot only when it is sparse.
    IfSparse,
}

impl ShotPolicy {
    pub fn from_args(args: &Value) -> Self {
        let screenshot_out_file = args
            .get("screenshot_out_file")
            .and_then(Value::as_str)
            .is_some_and(|path| !path.is_empty());
        match args.get("include_screenshot").and_then(Value::as_bool) {
            Some(true) => return ShotPolicy::Always(ShotReason::Requested),
            _ if screenshot_out_file => return ShotPolicy::Always(ShotReason::Requested),
            Some(false) => return ShotPolicy::Never,
            None => {}
        }
        if args
            .get("include_accessibility_tree")
            .and_then(Value::as_bool)
            == Some(false)
        {
            ShotPolicy::Always(ShotReason::NoTree)
        } else if marks_requested(args) {
            ShotPolicy::Always(ShotReason::Marks)
        } else if session_vision(args) {
            ShotPolicy::Always(ShotReason::Vision)
        } else {
            ShotPolicy::IfSparse
        }
    }

    /// The screenshot capture may be skipped only under `IfSparse`, and then
    /// only once the walk is known to have found enough elements.
    pub fn decide(self, walked_elements: Option<usize>) -> Option<ShotReason> {
        match self {
            ShotPolicy::Always(reason) => Some(reason),
            ShotPolicy::Never => None,
            ShotPolicy::IfSparse => match walked_elements {
                Some(n) if n >= SPARSE_TREE_ELEMENTS => None,
                Some(_) => Some(ShotReason::SparseTree),
                None => Some(ShotReason::NoTree),
            },
        }
    }
}

/// `structuredContent` note for a tree-first read that skipped the capture.
pub fn mark_screenshot_omitted(structured: &mut Value) {
    structured["screenshot_omitted"] =
        json!("tree_first: pass include_screenshot:true (or marks:true) to see the window");
}

// ── model-facing image ────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ShotFormat {
    Jpeg,
    Png,
}

impl ShotFormat {
    pub fn from_args(args: &Value) -> Result<Self, String> {
        match args.get("screenshot_format") {
            None | Some(Value::Null) => Ok(ShotFormat::Jpeg),
            Some(Value::String(s))
                if s.eq_ignore_ascii_case("jpeg") || s.eq_ignore_ascii_case("jpg") =>
            {
                Ok(ShotFormat::Jpeg)
            }
            Some(Value::String(s)) if s.eq_ignore_ascii_case("png") => Ok(ShotFormat::Png),
            _ => Err("screenshot_format must be \"jpeg\" or \"png\".".into()),
        }
    }

    pub fn mime_type(self) -> &'static str {
        match self {
            ShotFormat::Jpeg => "image/jpeg",
            ShotFormat::Png => "image/png",
        }
    }
}

pub fn marks_requested(args: &Value) -> bool {
    args.get("marks").and_then(Value::as_bool) == Some(true)
}

/// One set-of-marks label: row index and its frame in screenshot pixels.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Mark {
    pub index: u64,
    pub x: i64,
    pub y: i64,
    pub w: i64,
    pub h: i64,
}

/// Marks for the structured `elements` that carry a `screenshot_frame`.
pub fn marks_from_elements(elements: &Value) -> Vec<Mark> {
    let Some(elements) = elements.as_array() else {
        return Vec::new();
    };
    elements
        .iter()
        .filter_map(|entry| {
            let frame = entry.get("screenshot_frame")?;
            Some(Mark {
                index: entry.get("element_index")?.as_u64()?,
                x: frame.get("x")?.as_i64()?,
                y: frame.get("y")?.as_i64()?,
                w: frame.get("w")?.as_i64()?,
                h: frame.get("h")?.as_i64()?,
            })
        })
        .collect()
}

/// The image embedded in the response: `png` (the delivered, already
/// downscaled capture), with `marks` drawn when given, in `format`.
pub fn encode_for_model(png: &[u8], marks: Option<&[Mark]>, format: ShotFormat) -> Result<Vec<u8>> {
    if marks.is_none() && format == ShotFormat::Png {
        return Ok(png.to_vec());
    }
    let mut img = image::load_from_memory_with_format(png, ImageFormat::Png)?.to_rgba8();
    if let Some(marks) = marks {
        draw_marks(&mut img, marks);
    }
    let mut out = Vec::new();
    match format {
        ShotFormat::Png => DynamicImage::ImageRgba8(img)
            .write_to(&mut std::io::Cursor::new(&mut out), ImageFormat::Png)?,
        ShotFormat::Jpeg => {
            let rgb = DynamicImage::ImageRgba8(img).to_rgb8();
            image::codecs::jpeg::JpegEncoder::new_with_quality(&mut out, JPEG_QUALITY)
                .encode_image(&rgb)?;
        }
    }
    Ok(out)
}

const PALETTE: [[u8; 3]; 6] = [
    [230, 25, 75],
    [0, 130, 200],
    [60, 160, 60],
    [145, 30, 180],
    [245, 130, 48],
    [0, 128, 128],
];

/// 5x7 glyphs for 0-9, one byte per row, low 5 bits, MSB on the left.
const DIGITS: [[u8; 7]; 10] = [
    [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
    [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
    [0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F],
    [0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E],
    [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
    [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
    [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
    [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
    [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
    [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
];

/// Draw each mark's outline and an index label at its top-left corner.
/// Frames off the image or covering most of it (the window, its root pane)
/// get no mark; larger frames are drawn first so the labels of small
/// controls stay on top.
pub fn draw_marks(img: &mut RgbaImage, marks: &[Mark]) {
    let (iw, ih) = (i64::from(img.width()), i64::from(img.height()));
    if iw == 0 || ih == 0 {
        return;
    }
    // Glyph pixel size: 7 px digits only on thumbnails, so a label stays
    // legible on a typical window screenshot after JPEG encoding.
    let scale: i64 = match iw.max(ih) {
        ..400 => 1,
        400..1600 => 2,
        _ => 3,
    };
    let mut visible: Vec<Mark> = marks
        .iter()
        .copied()
        .filter(|m| {
            m.w > 0
                && m.h > 0
                && m.x < iw
                && m.y < ih
                && m.x + m.w > 0
                && m.y + m.h > 0
                && (m.w * m.h) * 2 < iw * ih
        })
        .collect();
    visible.sort_by_key(|m| std::cmp::Reverse(m.w * m.h));
    if visible.len() > MAX_MARKS {
        visible.drain(..visible.len() - MAX_MARKS);
    }
    for mark in &visible {
        let [r, g, b] = PALETTE[(mark.index as usize) % PALETTE.len()];
        let color = Rgba([r, g, b, 255]);
        outline(img, mark.x, mark.y, mark.w, mark.h, color);
        let text = mark.index.to_string();
        let label_w = (text.len() as i64) * 6 * scale + scale;
        let label_h = 9 * scale;
        // Inside the frame's top-left corner, kept on the image.
        let lx = mark.x.clamp(0, (iw - label_w).max(0));
        let ly = mark.y.clamp(0, (ih - label_h).max(0));
        fill(img, lx, ly, label_w, label_h, color);
        for (i, ch) in text.bytes().enumerate() {
            let glyph = &DIGITS[(ch - b'0') as usize];
            let gx = lx + scale + (i as i64) * 6 * scale;
            let gy = ly + scale;
            for (row, bits) in glyph.iter().enumerate() {
                for col in 0..5 {
                    if bits & (0x10 >> col) != 0 {
                        fill(
                            img,
                            gx + col * scale,
                            gy + row as i64 * scale,
                            scale,
                            scale,
                            Rgba([255, 255, 255, 255]),
                        );
                    }
                }
            }
        }
    }
}

fn fill(img: &mut RgbaImage, x: i64, y: i64, w: i64, h: i64, color: Rgba<u8>) {
    let (iw, ih) = (i64::from(img.width()), i64::from(img.height()));
    for py in y.max(0)..(y + h).min(ih) {
        for px in x.max(0)..(x + w).min(iw) {
            img.put_pixel(px as u32, py as u32, color);
        }
    }
}

fn outline(img: &mut RgbaImage, x: i64, y: i64, w: i64, h: i64, color: Rgba<u8>) {
    const T: i64 = 2;
    fill(img, x, y, w, T, color);
    fill(img, x, y + h - T, w, T, color);
    fill(img, x, y, T, h, color);
    fill(img, x + w - T, y, T, h, color);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn png(w: u32, h: u32) -> Vec<u8> {
        let img = RgbaImage::from_pixel(w, h, Rgba([250, 250, 250, 255]));
        let mut out = Vec::new();
        DynamicImage::ImageRgba8(img)
            .write_to(&mut std::io::Cursor::new(&mut out), ImageFormat::Png)
            .unwrap();
        out
    }

    #[test]
    fn default_read_is_tree_first_and_sparse_trees_get_a_screenshot() {
        let policy = ShotPolicy::from_args(&json!({"pid": 1, "window_id": 2}));
        assert_eq!(policy, ShotPolicy::IfSparse);
        assert_eq!(policy.decide(Some(40)), None);
        assert_eq!(policy.decide(Some(SPARSE_TREE_ELEMENTS)), None);
        assert_eq!(policy.decide(Some(3)), Some(ShotReason::SparseTree));
        assert_eq!(policy.decide(Some(0)), Some(ShotReason::SparseTree));
    }

    #[test]
    fn explicit_arguments_settle_the_screenshot() {
        let decide = |args: Value| ShotPolicy::from_args(&args).decide(Some(100));
        assert_eq!(
            decide(json!({"include_screenshot": true})),
            Some(ShotReason::Requested)
        );
        assert_eq!(
            decide(json!({"screenshot_out_file": "C:/x.png"})),
            Some(ShotReason::Requested)
        );
        assert_eq!(decide(json!({"marks": true})), Some(ShotReason::Marks));
        assert_eq!(
            decide(json!({"include_accessibility_tree": false})),
            Some(ShotReason::NoTree)
        );
        // An explicit false wins over marks, vision and a sparse tree.
        let never = ShotPolicy::from_args(&json!({"include_screenshot": false, "marks": true}));
        assert_eq!(never.decide(Some(0)), None);
        // screenshot_out_file still forces the capture, as upstream does.
        let file = ShotPolicy::from_args(
            &json!({"include_screenshot": false, "screenshot_out_file": "C:/x.png"}),
        );
        assert_eq!(file.decide(Some(100)), Some(ShotReason::Requested));
    }

    #[test]
    fn a_vision_session_gets_screenshots_until_it_ends() {
        let key = "dove-obs-test-vision";
        let read = json!({"session": key, "pid": 1, "window_id": 2});
        assert_eq!(ShotPolicy::from_args(&read), ShotPolicy::IfSparse);
        record_start_session(&json!({"session": key, "vision": true}));
        assert_eq!(
            ShotPolicy::from_args(&read),
            ShotPolicy::Always(ShotReason::Vision)
        );
        // Another session is unaffected.
        let other = json!({"session": "dove-obs-test-other"});
        assert_eq!(ShotPolicy::from_args(&other), ShotPolicy::IfSparse);
        // include_screenshot:false still opts a vision read out.
        let opt_out = json!({"session": key, "include_screenshot": false});
        assert_eq!(ShotPolicy::from_args(&opt_out), ShotPolicy::Never);
        // start_session without `vision` keeps the flag; vision:false clears it.
        record_start_session(&json!({"session": key}));
        assert!(session_vision(&read));
        record_start_session(&json!({"session": key, "vision": false}));
        assert!(!session_vision(&read));
        record_start_session(&json!({"session": key, "vision": true}));
        crate::session::fire_session_end(key);
        assert!(!session_vision(&read));
    }

    #[test]
    fn the_implicit_session_is_used_without_a_label() {
        let args = json!({"_session_id": "dove-obs-test-implicit", "vision": true});
        record_start_session(&args);
        assert!(session_vision(
            &json!({"_session_id": "dove-obs-test-implicit"})
        ));
        assert!(!session_vision(&json!({"session": "default"})));
    }

    #[test]
    fn screenshot_format_defaults_to_jpeg() {
        assert_eq!(ShotFormat::from_args(&json!({})), Ok(ShotFormat::Jpeg));
        assert_eq!(
            ShotFormat::from_args(&json!({"screenshot_format": "PNG"})),
            Ok(ShotFormat::Png)
        );
        assert!(ShotFormat::from_args(&json!({"screenshot_format": "gif"})).is_err());
    }

    #[test]
    fn jpeg_encoding_is_jpeg_and_png_without_marks_is_untouched() {
        let png = png(64, 32);
        let jpeg = encode_for_model(&png, None, ShotFormat::Jpeg).unwrap();
        assert_eq!(&jpeg[..3], &[0xFF, 0xD8, 0xFF]);
        assert_eq!(encode_for_model(&png, None, ShotFormat::Png).unwrap(), png);
    }

    #[test]
    fn marks_come_from_elements_with_a_screenshot_frame() {
        let elements = json!([
            {"element_index": 3, "screenshot_frame": {"x": 10, "y": 20, "w": 30, "h": 12}},
            {"element_index": 4},
            {"element_index": 5, "frame": {"x": 1, "y": 1, "w": 1, "h": 1}},
        ]);
        assert_eq!(
            marks_from_elements(&elements),
            vec![Mark {
                index: 3,
                x: 10,
                y: 20,
                w: 30,
                h: 12
            }]
        );
    }

    #[test]
    fn a_mark_draws_its_outline_and_label_and_skips_the_window_itself() {
        let mut img = RgbaImage::from_pixel(200, 100, Rgba([250, 250, 250, 255]));
        let marks = [
            Mark {
                index: 7,
                x: 40,
                y: 30,
                w: 60,
                h: 30,
            },
            // Covers the whole image: the window, not a control.
            Mark {
                index: 0,
                x: 0,
                y: 0,
                w: 200,
                h: 100,
            },
        ];
        draw_marks(&mut img, &marks);
        let [r, g, b] = PALETTE[7 % PALETTE.len()];
        // Bottom-right of the outline.
        assert_eq!(img.get_pixel(99, 59), &Rgba([r, g, b, 255]));
        // Label background at the frame's top-left, with a white glyph pixel
        // ("7" starts with a full top row).
        assert_eq!(img.get_pixel(40, 30), &Rgba([r, g, b, 255]));
        assert_eq!(img.get_pixel(41, 31), &Rgba([255, 255, 255, 255]));
        // Nothing drawn for the window-sized frame's corner.
        assert_eq!(img.get_pixel(199, 99), &Rgba([250, 250, 250, 255]));
    }

    #[test]
    fn labels_stay_on_the_image() {
        let mut img = RgbaImage::from_pixel(50, 20, Rgba([0, 0, 0, 255]));
        draw_marks(
            &mut img,
            &[Mark {
                index: 123,
                x: 45,
                y: 15,
                w: 4,
                h: 4,
            }],
        );
        // The 3-digit label (19x9 px) is moved left and up so it is fully
        // visible: its left edge is at 50 - 19 and its top at 20 - 9.
        let [r, g, b] = PALETTE[123 % PALETTE.len()];
        assert_eq!(img.get_pixel(31, 11), &Rgba([r, g, b, 255]));
        assert_eq!(img.get_pixel(30, 11), &Rgba([0, 0, 0, 255]));
    }

    #[test]
    fn labels_scale_with_the_image() {
        // A 600 px window gets 2x glyphs: the label for "1" is 14x18 px.
        let mut img = RgbaImage::from_pixel(600, 400, Rgba([250, 250, 250, 255]));
        draw_marks(
            &mut img,
            &[Mark {
                index: 1,
                x: 100,
                y: 100,
                w: 80,
                h: 30,
            }],
        );
        let [r, g, b] = PALETTE[1];
        assert_eq!(img.get_pixel(113, 117), &Rgba([r, g, b, 255]));
        assert_eq!(img.get_pixel(114, 117), &Rgba([250, 250, 250, 255]));
    }

    #[test]
    fn marked_png_round_trips() {
        let png = png(120, 80);
        let marks = [Mark {
            index: 12,
            x: 5,
            y: 5,
            w: 40,
            h: 20,
        }];
        let out = encode_for_model(&png, Some(&marks), ShotFormat::Png).unwrap();
        let img = image::load_from_memory(&out).unwrap().to_rgba8();
        assert_ne!(img.get_pixel(6, 6), &Rgba([250, 250, 250, 255]));
    }
}
