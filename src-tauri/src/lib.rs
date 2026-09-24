//! PULSEFRAME desktop core: projects on disk, OS keychain, and the analysis/director engine.
//!
//! The engine (Python) runs as a hidden background process; its JSON-line progress is
//! forwarded to the UI as `engine-progress` events. Provider keys live only in the OS
//! credential store and are handed to an engine process through its environment.

use serde_json::{json, Value};
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use tauri::{AppHandle, Emitter, Manager};

const KEY_SERVICE: &str = "pulseframe";
const PROVIDERS: [&str; 3] = ["openai", "fal", "kie"];

fn err<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

fn projects_root(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().document_dir().map_err(err)?.join("PULSEFRAME");
    fs::create_dir_all(&dir).map_err(err)?;
    Ok(dir)
}

/// Development layout: the engine lives next to src-tauri. Packaging replaces this with a bundled sidecar.
fn engine_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("analysis")
}

fn engine_python() -> PathBuf {
    let venv = engine_dir().join(".venv");
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn read_json(path: &Path) -> Option<Value> {
    fs::read_to_string(path).ok().and_then(|s| serde_json::from_str(&s).ok())
}

fn write_json(path: &Path, v: &Value) -> Result<(), String> {
    // Write-then-rename so a crash never leaves a half-written project file.
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, serde_json::to_string_pretty(v).map_err(err)?).map_err(err)?;
    fs::rename(&tmp, path).map_err(err)
}

fn update_project(dir: &Path, patch: Value) -> Result<(), String> {
    let path = dir.join("project.json");
    let mut p = read_json(&path).unwrap_or_else(|| json!({}));
    if let (Some(obj), Some(add)) = (p.as_object_mut(), patch.as_object()) {
        for (k, v) in add {
            obj.insert(k.clone(), v.clone());
        }
    }
    write_json(&path, &p)
}

/// Run one engine job, forwarding progress lines to the UI. Returns stderr tail on failure.
fn run_engine(app: &AppHandle, job: &str, args: &[String], envs: &[(&str, String)]) -> Result<(), String> {
    run_engine_result(app, job, args, envs).map(|_| ())
}

/// Like run_engine, but returns the `data` of the engine's final `{"event":"result"}` line.
fn run_engine_result(app: &AppHandle, job: &str, args: &[String], envs: &[(&str, String)]) -> Result<Value, String> {
    let mut cmd = Command::new(engine_python());
    cmd.args(args)
        .current_dir(engine_dir())
        .env("PYTHONIOENCODING", "utf-8")
        .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (k, v) in envs {
        cmd.env(k, v);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: never flash a console at the user
    }
    let mut child = cmd.spawn().map_err(|e| format!("Could not start the engine: {e}"))?;
    let mut stderr = child.stderr.take().unwrap();
    let err_thread = std::thread::spawn(move || {
        let mut s = String::new();
        let _ = stderr.read_to_string(&mut s);
        s
    });
    let mut engine_error: Option<String> = None;
    let mut result = Value::Null;
    for line in BufReader::new(child.stdout.take().unwrap()).lines().map_while(Result::ok) {
        if let Ok(mut v) = serde_json::from_str::<Value>(&line) {
            if v["event"] == "error" {
                engine_error = v["message"].as_str().map(String::from);
            }
            if v["event"] == "result" {
                result = v["data"].take();
                continue;
            }
            v["task"] = json!(job);
            let _ = app.emit("engine-progress", v);
        }
    }
    let status = child.wait().map_err(err)?;
    let stderr_text = err_thread.join().unwrap_or_default();
    if status.success() && engine_error.is_none() {
        return Ok(result);
    }
    let tail: String = stderr_text.lines().rev().take(6).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n");
    Err(engine_error.unwrap_or(tail))
}

fn slug(title: &str) -> String {
    let s: String = title
        .chars()
        .map(|c| if c.is_alphanumeric() || c == ' ' || c == '-' { c } else { ' ' })
        .collect();
    let s = s.split_whitespace().collect::<Vec<_>>().join(" ");
    if s.is_empty() { "Untitled".into() } else { s }
}

// ---------- splash ----------

static LAUNCHED: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
const SPLASH_MIN: std::time::Duration = std::time::Duration::from_millis(1200);

/// Called by the UI after its first paint: keep the splash for a short minimum so it never
/// flickers, then close it and reveal the fully drawn main window.
#[tauri::command]
async fn app_ready(app: AppHandle) {
    let started = *LAUNCHED.get_or_init(std::time::Instant::now);
    if let Some(rest) = SPLASH_MIN.checked_sub(started.elapsed()) {
        tokio_sleep(rest).await;
    }
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.set_focus();
    }
    if let Some(splash) = app.get_webview_window("splashscreen") {
        let _ = splash.close();
    }
}

async fn tokio_sleep(d: std::time::Duration) {
    let _ = tauri::async_runtime::spawn_blocking(move || std::thread::sleep(d)).await;
}

// ---------- keys ----------

#[tauri::command]
fn key_status() -> Value {
    let mut out = serde_json::Map::new();
    for p in PROVIDERS {
        let ok = keyring::Entry::new(KEY_SERVICE, p)
            .and_then(|e| e.get_password())
            .map(|k| !k.is_empty())
            .unwrap_or(false);
        out.insert(p.into(), json!(ok));
    }
    Value::Object(out)
}

#[tauri::command]
fn set_key(provider: String, key: String) -> Result<(), String> {
    if !PROVIDERS.contains(&provider.as_str()) {
        return Err("Unknown provider".into());
    }
    let key = key.trim();
    if key.is_empty() {
        return Err("Key is empty".into());
    }
    keyring::Entry::new(KEY_SERVICE, &provider).and_then(|e| e.set_password(key)).map_err(err)
}

#[tauri::command]
fn delete_key(provider: String) -> Result<(), String> {
    match keyring::Entry::new(KEY_SERVICE, &provider).and_then(|e| e.delete_credential()) {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(err(e)),
    }
}

// ---------- projects ----------

/// Read a user-chosen text file (lyrics). Only reachable via the native file picker in the UI.
#[tauri::command]
fn read_text(path: String) -> Result<String, String> {
    let meta = fs::metadata(&path).map_err(err)?;
    if meta.len() > 2_000_000 {
        return Err("That file is too large to be lyrics.".into());
    }
    fs::read_to_string(&path).map_err(|_| "Could not read that file as text.".into())
}

#[tauri::command]
fn list_projects(app: AppHandle) -> Result<Vec<Value>, String> {
    let mut out = vec![];
    for entry in fs::read_dir(projects_root(&app)?).map_err(err)?.flatten() {
        let dir = entry.path();
        if let Some(mut p) = read_json(&dir.join("project.json")) {
            let modified = entry.metadata().and_then(|m| m.modified()).ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs()).unwrap_or(0);
            p["dir"] = json!(dir.to_string_lossy());
            p["modified"] = json!(modified);
            out.push(p);
        }
    }
    out.sort_by(|a, b| b["modified"].as_u64().cmp(&a["modified"].as_u64()));
    Ok(out)
}

#[tauri::command]
fn create_project(app: AppHandle, song_path: String, title: String, lyrics: Option<String>,
                  script_path: Option<String>, look: Option<Value>) -> Result<String, String> {
    let root = projects_root(&app)?;
    let base = slug(&title);
    let mut dir = root.join(format!("{base}.pulseframe"));
    let mut n = 2;
    while dir.exists() {
        dir = root.join(format!("{base} {n}.pulseframe"));
        n += 1;
    }
    for sub in ["assets", "generations", "thumbnails", "cache", "exports"] {
        fs::create_dir_all(dir.join(sub)).map_err(err)?;
    }
    let src = Path::new(&song_path);
    let ext = src.extension().and_then(|e| e.to_str()).unwrap_or("wav").to_lowercase();
    let song = format!("song.{ext}");
    fs::copy(src, dir.join(&song)).map_err(|e| format!("Could not copy the song: {e}"))?;
    let mut project = json!({
        "schema_version": 1, "title": title, "song": song, "source_song": song_path,
        "created": std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0),
        "state": "new",
        "look": look.unwrap_or_else(|| json!({"style": "auto"})),
    });
    if let Some(l) = lyrics.filter(|l| !l.trim().is_empty()) {
        fs::write(dir.join("lyrics.txt"), l).map_err(err)?;
        project["lyrics"] = json!("lyrics.txt");
    }
    if let Some(sp) = script_path.filter(|s| !s.is_empty()) {
        let sp = Path::new(&sp);
        let sext = sp.extension().and_then(|e| e.to_str()).unwrap_or("txt").to_lowercase();
        let name = format!("script.{sext}");
        fs::copy(sp, dir.join(&name)).map_err(|e| format!("Could not copy the script: {e}"))?;
        project["script"] = json!(name);
    }
    write_json(&dir.join("project.json"), &project)?;
    Ok(dir.to_string_lossy().into())
}

#[tauri::command]
fn load_project(dir: String) -> Result<Value, String> {
    let d = Path::new(&dir);
    let project = read_json(&d.join("project.json")).ok_or("This project could not be opened.")?;
    let song = project["song"].as_str().map(|s| d.join(s).to_string_lossy().to_string());
    Ok(json!({
        "dir": dir,
        "project": project,
        "song_path": song,
        "song_map": read_json(&d.join("songmap.json")),
        "production": read_json(&d.join("production.json")),
        "directed": read_json(&d.join("directed.json")),
        "jobs": read_json(&d.join("jobs.json")).map(|j| j["jobs"].clone()).unwrap_or(json!([])),
    }))
}

#[tauri::command]
async fn analyze_project(app: AppHandle, dir: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        let d = PathBuf::from(&dir);
        let project = read_json(&d.join("project.json")).ok_or("Missing project file")?;
        let p = |k: &str| d.join(k).to_string_lossy().to_string();
        update_project(&d, json!({"state": "analyzing"}))?;
        let mut args = vec!["-m".into(), "pulseframe_analysis".into(),
                            p(project["song"].as_str().unwrap_or("song.wav")),
                            "--out".into(), p("songmap.json"), "--work-dir".into(), p("cache/stems")];
        if let Some(l) = project["lyrics"].as_str() {
            args.push("--lyrics".into());
            args.push(p(l));
        }
        run_engine(&app, "analysis", &args, &[])?;
        if let Some(s) = project["script"].as_str() {
            let _ = app.emit("engine-progress", json!({"task": "analysis", "stage": "script", "progress": 1.0}));
            run_engine(&app, "script", &["-m".into(), "pulseframe_analysis.script_import".into(),
                                         p(s), p("songmap.json"), p("production.json")], &[])?;
        }
        update_project(&d, json!({"state": "analyzed"}))
    })
    .await
    .map_err(err)?
}

#[tauri::command]
async fn direct_project(app: AppHandle, dir: String) -> Result<(), String> {
    let key = keyring::Entry::new(KEY_SERVICE, "openai")
        .and_then(|e| e.get_password())
        .map_err(|_| "Add your OpenAI key in Settings to direct the video.".to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        let d = PathBuf::from(&dir);
        if !d.join("production.json").exists() {
            return Err("This project has no script plan to direct yet.".into());
        }
        let p = |k: &str| d.join(k).to_string_lossy().to_string();
        run_engine(&app, "director", &["-m".into(), "pulseframe_analysis.director".into(),
                                       p("production.json"), p("songmap.json"), "--out".into(), p("directed.json")],
                   &[("PULSEFRAME_OPENAI_KEY", key)])?;
        update_project(&d, json!({"state": "directed"}))
    })
    .await
    .map_err(err)?
}

// ---------- rendering ----------

fn provider_env() -> Vec<(&'static str, String)> {
    let mut env = vec![];
    for (provider, var) in [("fal", "FAL_KEY"), ("kie", "KIE_KEY")] {
        if let Ok(k) = keyring::Entry::new(KEY_SERVICE, provider).and_then(|e| e.get_password()) {
            env.push((var, k));
        }
    }
    env
}

fn render_args(sub: &str, rest: &[String]) -> Vec<String> {
    let mut a = vec!["-m".to_string(), "pulseframe_analysis.render".into(), sub.into()];
    a.extend_from_slice(rest);
    a
}

/// Project folders with a live background renderer, so we never start two for one project.
static RUNNERS: std::sync::Mutex<Vec<String>> = std::sync::Mutex::new(Vec::new());

/// Start (or keep) the background renderer for a project. It drives every queued/in-flight job,
/// including ones left running when the app was closed, then exits.
#[tauri::command]
fn ensure_renderer(app: AppHandle, dir: String) {
    {
        let mut r = RUNNERS.lock().unwrap();
        if r.contains(&dir) {
            return;
        }
        r.push(dir.clone());
    }
    std::thread::spawn(move || {
        let res = run_engine(&app, "render", &render_args("run", &[dir.clone()]), &provider_env());
        RUNNERS.lock().unwrap().retain(|d| d != &dir);
        let _ = app.emit("render-idle", json!({"dir": dir, "error": res.err()}));
    });
}

#[tauri::command]
async fn render_catalog(app: AppHandle, provider: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "catalog", &render_args("catalog", &["--provider".into(), provider]), &[])
    }).await.map_err(err)?
}

#[tauri::command]
async fn model_manifest(app: AppHandle, provider: String, model: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "manifest", &render_args("manifest", &["--provider".into(), provider, "--model".into(), model]), &[])
    }).await.map_err(err)?
}

fn shot_args(dir: String, shots: Vec<String>, provider: String, model: Option<String>, overrides: Value) -> Vec<String> {
    let mut a = vec![dir, "--shots".into(), shots.join(","), "--provider".into(), provider,
                     "--overrides".into(), overrides.to_string()];
    if let Some(m) = model.filter(|m| !m.is_empty()) {
        a.push("--model".into());
        a.push(m);
    }
    a
}

/// Exactly what would be sent for one shot. Uploads nothing and costs nothing.
#[tauri::command]
async fn render_preview(app: AppHandle, dir: String, shot: String, provider: String, model: Option<String>,
                        overrides: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "preview", &render_args("preview", &shot_args(dir, vec![shot], provider, model, overrides)), &[])
    }).await.map_err(err)?
}

/// Queue shots for rendering (billable once the renderer sends them) and start the renderer.
#[tauri::command]
async fn queue_render(app: AppHandle, dir: String, shots: Vec<String>, provider: String, model: Option<String>,
                      overrides: Value) -> Result<Value, String> {
    let key_ok = keyring::Entry::new(KEY_SERVICE, &provider).and_then(|e| e.get_password()).is_ok();
    if !key_ok {
        return Err(format!("Add your {} key in Settings first.", if provider == "fal" { "fal.ai" } else { "Kie.ai" }));
    }
    let app2 = app.clone();
    let d2 = dir.clone();
    let made = tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app2, "enqueue", &render_args("enqueue", &shot_args(d2, shots, provider, model, overrides)), &[])
    }).await.map_err(err)??;
    ensure_renderer(app, dir);
    Ok(made)
}

#[tauri::command]
async fn resolve_job(app: AppHandle, dir: String, job: String, action: String) -> Result<Value, String> {
    let app2 = app.clone();
    let d2 = dir.clone();
    let res = tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app2, "resolve", &render_args("resolve", &[d2, "--job".into(), job, "--action".into(), action]), &[])
    }).await.map_err(err)??;
    ensure_renderer(app, dir);
    Ok(res)
}

// ---------- looks ----------

#[tauri::command]
fn list_styles() -> Result<Value, String> {
    read_json(&engine_dir().join("pulseframe_analysis").join("styles.json"))
        .map(|v| v["styles"].clone())
        .ok_or_else(|| "The look library is missing.".into())
}

/// look: {"style": id, "notes"?: str, "prompt"?: str, "avoid"?: str}. Applies to every future render.
#[tauri::command]
fn set_look(dir: String, look: Value) -> Result<(), String> {
    if !look["style"].is_string() {
        return Err("Choose a look.".into());
    }
    update_project(Path::new(&dir), json!({ "look": look }))
}

// ---------- export ----------

#[tauri::command]
async fn export_project(app: AppHandle, dir: String, preset: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "export", &["-m".into(), "pulseframe_analysis.export".into(), dir, "--preset".into(), preset], &[])
    }).await.map_err(err)?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    LAUNCHED.get_or_init(std::time::Instant::now);
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Safety net: never leave the user staring at the splash if the UI fails to report ready.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(8));
                if let Some(main) = handle.get_webview_window("main") {
                    if !main.is_visible().unwrap_or(true) {
                        let _ = main.show();
                    }
                }
                if let Some(splash) = handle.get_webview_window("splashscreen") {
                    let _ = splash.close();
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            key_status, set_key, delete_key, read_text, list_projects, create_project, load_project,
            analyze_project, direct_project, ensure_renderer, render_catalog, model_manifest, render_preview,
            queue_render, resolve_job, export_project, list_styles, set_look, app_ready
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keychain_round_trip() {
        // Uses a throwaway entry so a real provider key is never touched.
        let e = keyring::Entry::new("pulseframe-selftest", "probe").unwrap();
        e.set_password("s3cret-value").unwrap();
        assert_eq!(e.get_password().unwrap(), "s3cret-value");
        e.delete_credential().unwrap();
        assert!(matches!(e.get_password(), Err(keyring::Error::NoEntry)));
    }

    #[test]
    fn slug_is_filesystem_safe() {
        assert_eq!(slug("Exit Plan: Remix/2"), "Exit Plan Remix 2");
        assert_eq!(slug("???"), "Untitled");
    }

    #[test]
    fn loads_a_real_project_when_present() {
        let Some(docs) = std::env::var_os("USERPROFILE").map(|h| PathBuf::from(h).join("Documents/PULSEFRAME/Exit Plan.pulseframe")) else { return };
        if !docs.exists() { return; }
        let v = load_project(docs.to_string_lossy().into()).unwrap();
        assert_eq!(v["project"]["title"], "Exit Plan");
        assert!(v["song_map"]["peaks"].as_array().unwrap().len() == 2000);
        let shots: usize = v["production"]["scenes"].as_array().unwrap().iter()
            .map(|s| s["shots"].as_array().unwrap().len()).sum();
        assert_eq!(shots, 70);
        assert!(Path::new(v["song_path"].as_str().unwrap()).exists());
    }

    #[test]
    fn engine_python_exists() {
        assert!(engine_python().exists(), "engine venv missing at {:?}", engine_python());
    }
}
