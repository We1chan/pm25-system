"""编排一次实时采集、HDFS 入库、Spark 特征构建和已训练模型推理。
读取配置与轮次参数，输出本轮原始资料、预测快照及各阶段进度。"""

import argparse, json, os, shutil, subprocess, sys, uuid
from pathlib import Path
from live_common import ROOT, now, progress


def run(args, **kw):
    """执行流水线子命令并保留日志，失败时立即停止后续发布。"""
    print("Running:", Path(str(args[0])).name, " ".join(str(v) for v in args[1:3]), flush=True)
    subprocess.run([str(v) for v in args], cwd=ROOT, check=True, **kw)


def main():
    """按命令行参数完成本模块流程，输入输出约定见模块说明。"""
    p = argparse.ArgumentParser()
    p.add_argument("--cycle")
    a = p.parse_args()
    cycle = a.cycle or now().strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    if not all(c.isalnum() or c in "_-" for c in cycle):
        raise ValueError("Invalid cycle ID")
    try:
        progress("collecting", cycle_id=cycle, started_at=now().isoformat())
        windows_python = Path("/mnt/c/Python314/python.exe")
        if sys.platform == "linux" and windows_python.exists():
            script = subprocess.check_output(
                ["wslpath", "-m", str(ROOT / "scripts/fetch_live_data.py")], text=True
            ).strip()
            run([windows_python, script, "--cycle", cycle], timeout=240)
        else:
            run(
                [sys.executable, ROOT / "scripts/fetch_live_data.py", "--cycle", cycle], timeout=240
            )
        config = json.loads((ROOT / "config.json").read_text())
        base = config["hdfs_root"] + "/live_v1/cycles/" + cycle
        environment = {**os.environ, "JAVA_HOME": "/usr/lib/jvm/java-11-openjdk-amd64"}
        hdfs = "/usr/local/hadoop/bin/hdfs"
        progress("spark", cycle_id=cycle)
        try:
            run([hdfs, "dfs", "-mkdir", "-p", base], env=environment, timeout=25)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            helper = shutil.which("hadoopctl")
            if not helper:
                raise
            run([helper, "start"], timeout=120)
            run([hdfs, "dfs", "-mkdir", "-p", base], env=environment, timeout=25)
        folder = ROOT / "data/live/cycles" / cycle
        run([hdfs, "dfs", "-put", "-f", folder / "raw", base + "/"], env=environment, timeout=120)
        run(
            [hdfs, "dfs", "-put", "-f", folder / "manifest.json", base + "/"],
            env=environment,
            timeout=30,
        )
        spark_timeout = int(os.environ.get("PM25_SPARK_TIMEOUT_SECONDS", "240"))
        run(["bash", "scripts/run_spark.sh", "live-prepare", "--cycle", cycle], timeout=spark_timeout)
        progress("inference", cycle_id=cycle)
        predictor = (
            "scripts/predict_forecast_live.py"
            if (ROOT / "models/forecast_tcn9.pt").exists()
            else "scripts/predict_live.py"
        )
        run([sys.executable, predictor, "--cycle", cycle], timeout=90)
        run(
            [hdfs, "dfs", "-put", "-f", folder / "forecast.json", base + "/"],
            env=environment,
            timeout=30,
        )
        progress("complete", cycle_id=cycle, completed_at=now().isoformat())
    except Exception as e:
        progress(
            "failed",
            cycle_id=cycle,
            error="实时更新未完成，请检查网络或 Hadoop 服务后重试",
            technical_error=str(e)[:400],
        )
        raise


if __name__ == "__main__":
    main()
