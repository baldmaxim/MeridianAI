//! `src/bindings.ts` is generated from the commands and events of
//! `specta_builder()` at the start of a debug build. This test keeps it from
//! drifting: it fails when the file differs from what the code produces, and
//! `UPDATE_BINDINGS=1 cargo test bindings` rewrites the file without starting the app.

use specta_typescript::{BigIntExportBehavior, Typescript};

const COMMITTED: &str = "../src/bindings.ts";

fn exporter() -> Typescript {
    Typescript::default().bigint(BigIntExportBehavior::Number)
}

#[test]
fn bindings_match_the_commands() {
    if std::env::var("UPDATE_BINDINGS").is_ok_and(|v| v == "1") {
        crate::specta_builder()
            .export(exporter(), COMMITTED)
            .expect("export bindings");
        return;
    }
    let dir = tempfile::tempdir().expect("temp dir");
    let generated = dir.path().join("bindings.ts");
    crate::specta_builder()
        .export(exporter(), &generated)
        .expect("export bindings");
    let fresh = std::fs::read_to_string(&generated).expect("read generated");
    let committed = std::fs::read_to_string(COMMITTED).expect("read src/bindings.ts");
    assert!(
        fresh == committed,
        "src/bindings.ts is out of date: run `UPDATE_BINDINGS=1 cargo test bindings`"
    );
}
