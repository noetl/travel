//! Validation adapter only: executes the one-step playbooks through the unmodified
//! upstream Rust PostgresTool and template engine. NOT a NoETL server/worker emulator.
use anyhow::{bail, Context, Result};
use noetl_tools::{context::ExecutionContext, registry::{Tool, ToolConfig}, tools::PostgresTool};
use serde_json::{json, Value};

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 { bail!("usage: adiona-noetl-validation PLAYBOOK LOGIN REQUEST_JSON"); }
    let login = &args[2];
    // Validation is deliberately confined to this disposable loopback database.
    if !login.starts_with("av_") && login != "migration_owner" { bail!("validation login required"); }
    let value: Value = serde_yaml::from_str(&std::fs::read_to_string(&args[1])?)?;
    let steps = value["workflow"].as_array().context("workflow array")?;
    if steps.len() != 1 || steps[0]["step"] != "start" { bail!("only one real PostgresTool call supported"); }
    let mut cfg = steps[0]["tool"].clone();
    if cfg["kind"] != "postgres" { bail!("postgres required"); }
    cfg.as_object_mut().unwrap().remove("auth");
    cfg["host"] = json!("127.0.0.1");
    cfg["port"] = json!(55439);
    cfg["database"] = json!("adiona_validation");
    cfg["user"] = json!(login);
    let config: ToolConfig = serde_json::from_value(cfg)?;
    let mut ctx = ExecutionContext::new(1, "start", "");
    ctx.set_variable("request", serde_json::from_str::<Value>(&args[3])?);
    let result = PostgresTool::new().execute(&config, &ctx).await?;
    println!("{}", serde_json::to_string(&result.data)?);
    Ok(())
}
