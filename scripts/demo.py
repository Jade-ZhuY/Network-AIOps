import argparse
import json

from app.config import Settings
from app.graph.workflow import WorkflowService

QUESTIONS = (
    "OSPF 为什么使用链路状态数据库？与 RIP 的收敛机制有什么区别？",
    "查询 R2 昨天有多少严重告警，eth1 的平均丢包率是多少？",
    "R2 昨天下午频繁发生 BGP 邻居断连，结合接口丢包率和告警记录分析可能原因。",
    "分析 R3 昨天下午 OSPF 邻居未建立的可能原因。",
    "分析 R4 昨天下午链路利用率突增与高 RTT 的原因。",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--question")
    parser.add_argument("--backend", choices=["mock", "mysql"])
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    settings = Settings(**({"data_backend": args.backend} if args.backend else {}))
    service = WorkflowService(settings)
    try:
        for question in QUESTIONS if args.all else [args.question or QUESTIONS[2]]:
            print(json.dumps(service.run(question), ensure_ascii=False, indent=2))
    finally:
        service.close()


if __name__ == "__main__":
    main()
