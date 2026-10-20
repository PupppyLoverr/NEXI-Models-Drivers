//! Dove fork: environment aliases.
//!
//! The driver reads upstream's `CUA_DRIVER_*` variables. Every
//! `DOVE_DRIVER_<NAME>` the caller sets is copied to `CUA_DRIVER_<NAME>`
//! when that is unset, so Dove can configure the driver under its own names
//! while upstream's names keep working. `DOVE_DRIVER_HOME` also fills
//! `CUA_DRIVER_RS_HOME`, the home override most of the driver reads.
//!
//! Runs first in `main`, before any thread starts.

use std::ffi::{OsStr, OsString};

/// Dove's plugin manager installs and updates dove-driver, so the driver
/// never queries upstream releases or runs upstream's installer.
pub const UPDATES_MANAGED_BY_DOVE: bool = true;
pub const UPDATES_MESSAGE: &str =
    "dove-driver does not update itself: Dove installs and updates it \
     (Settings > Integrations > Computer use)";

const DOVE_PREFIX: &str = "DOVE_DRIVER_";
const UPSTREAM_PREFIX: &str = "CUA_DRIVER_";

pub fn apply_aliases() {
    for (name, value) in aliases(std::env::vars_os()) {
        if name == "CUA_DRIVER_HOME" {
            set_if_unset("CUA_DRIVER_RS_HOME", &value);
        }
        set_if_unset(&name, &value);
    }
}

/// The upstream name for each `DOVE_DRIVER_*` variable, with its value.
fn aliases(vars: impl Iterator<Item = (OsString, OsString)>) -> Vec<(String, OsString)> {
    vars.filter_map(|(key, value)| {
        let suffix = key.to_str()?.strip_prefix(DOVE_PREFIX)?;
        (!suffix.is_empty()).then(|| (format!("{UPSTREAM_PREFIX}{suffix}"), value))
    })
    .collect()
}

fn set_if_unset(name: &str, value: &OsStr) {
    if std::env::var_os(name).is_none() {
        std::env::set_var(name, value);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vars(pairs: &[(&str, &str)]) -> impl Iterator<Item = (OsString, OsString)> {
        pairs
            .iter()
            .map(|(k, v)| (OsString::from(k), OsString::from(v)))
            .collect::<Vec<_>>()
            .into_iter()
    }

    #[test]
    fn dove_names_map_to_upstream_names() {
        let mapped = aliases(vars(&[
            ("DOVE_DRIVER_HOME", "/d"),
            ("DOVE_DRIVER_PERMISSION_MODE", "bounded"),
            ("DOVE_DRIVER_", "ignored"),
            ("CUA_DRIVER_HOME", "/c"),
            ("PATH", "/bin"),
        ]));
        assert_eq!(
            mapped,
            vec![
                ("CUA_DRIVER_HOME".to_owned(), OsString::from("/d")),
                ("CUA_DRIVER_PERMISSION_MODE".to_owned(), OsString::from("bounded")),
            ]
        );
    }

    #[test]
    fn an_upstream_value_already_set_wins() {
        let name = "CUA_DRIVER_DOVE_ENV_TEST_KEEP";
        std::env::set_var(name, "upstream");
        set_if_unset(name, OsStr::new("dove"));
        assert_eq!(std::env::var(name).as_deref(), Ok("upstream"));
        std::env::remove_var(name);
        set_if_unset(name, OsStr::new("dove"));
        assert_eq!(std::env::var(name).as_deref(), Ok("dove"));
        std::env::remove_var(name);
    }
}
