"""命令行适配层。

职责：解析命令行参数并调用 Orchestrator；不承载 State、Runner 或任务逻辑。
"""

import argparse

from .config import Config
from .orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(prog="wenyi")
    parser.add_argument("command", choices=["ingest", "translate", "export"])
    parser.add_argument(
        "target",
        help="ingest 使用原始文件路径；translate/export 使用具体 State 目录名",
    )
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument(
        "--format",
        default="epub",
        choices=["epub", "txt", "html", "markdown", "pdf"],
        help="export 输出格式",
    )
    parser.add_argument("--out", help="export 输出文件路径")
    args = parser.parse_args()

    config = Config.load(args.config)
    orchestrator = Orchestrator(config)
    if args.command == "ingest":
        store = orchestrator.ingest(args.target)
        print(store.run_dir)
    elif args.command == "translate":
        orchestrator.translate(args.target)
    else:
        print(
            orchestrator.export(
                args.target,
                out_format=args.format,
                out_path=args.out,
            )
        )
