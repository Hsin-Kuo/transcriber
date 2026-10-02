#!/usr/bin/env python3
"""產生四份最小權限 policy。這裡是唯一來源——**別手改 JSON**，改這支再重跑：

    python3 deploy/iam/generate-policies.py && bash deploy/iam/update-policies.sh

權限依據（2026-10-01 以 grep 實證，見 README）：
  web    讀 jwt/金流/寄信相關；只對 SQS SendMessage
  worker 讀 mongodb/worker-secret/gemini/hf；只對 SQS Receive/Delete，可關自己那群機器
"""
import json, pathlib

A, R = "696637902131", "ap-northeast-1"
OUT = pathlib.Path(__file__).parent

# src/main.py, routers/, utils/{payments91,smilepay,email_service,card_token_cipher}
WEB = ["jwt-secret", "mongodb-url", "worker-secret", "google-client-id", "card-token-kek",
       "91app-*", "smilepay-*", "resend-api-key", "resend-webhook-secret",
       "email-provider", "from-email"]
# src/worker_core/config.py, worker_core/model_cache.py
WORKER = ["mongodb-url", "worker-secret", "google-api-key-1", "google-api-key-2", "hf-token"]


def build(env: str, kind: str) -> dict:
    pfx    = "transcriber" if env == "prod" else "transcriber-staging"
    bucket = f"transcriber-files-{A}" if env == "prod" else f"transcriber-files-staging-{A}"
    queues = ["transcriber-tasks", "transcriber-tasks-priority"] if env == "prod" else \
             ["transcriber-tasks-staging", "transcriber-tasks-staging-priority"]
    qarn   = [f"arn:aws:sqs:{R}:{A}:{q}" for q in queues]
    params = [f"arn:aws:ssm:{R}:{A}:parameter/{pfx}/{n}"
              for n in (WEB if kind == "web" else WORKER)]
    E = env.capitalize()

    st = [
        {"Sid": f"{E}Secrets{kind.capitalize()}Only", "Effect": "Allow",
         "Action": ["ssm:GetParameter", "ssm:GetParameters"], "Resource": params},
        # AmazonSSMManagedInstanceCore 帶 ssm:GetParameter on "*"，會架空上面的範圍限定。
        # explicit Deny 優先於任何 Allow，這條才是真正的隔離。/aws/* 留給 ssm-agent。
        {"Sid": "DenyAnyOtherParameter", "Effect": "Deny",
         "Action": ["ssm:GetParameter", "ssm:GetParameters"],
         "NotResource": params + ["arn:aws:ssm:*:*:parameter/aws/*"]},
        {"Sid": f"{E}BucketOnly", "Effect": "Allow",
         "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
         "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"]},
    ]
    if kind == "web":
        st.append({"Sid": f"{E}QueueSendOnly", "Effect": "Allow",
                   "Action": ["sqs:SendMessage", "sqs:GetQueueAttributes"], "Resource": qarn})
    else:
        tags = ["transcriber-gpu-worker", "transcriber-gpu-ondemand"] if env == "prod" \
               else "transcriber-gpu-staging"
        st += [
            {"Sid": f"{E}QueueConsumeOnly", "Effect": "Allow",
             "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage",
                        "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"],
             "Resource": qarn},
            # 舊 transcriber-ec2-policy 這條是 instance/* 無 Condition，等於全帳號可停。
            {"Sid": "SelfStopTaggedOnly", "Effect": "Allow", "Action": "ec2:StopInstances",
             "Resource": f"arn:aws:ec2:{R}:{A}:instance/*",
             "Condition": {"StringEquals": {"ec2:ResourceTag/Name": tags}}},
            {"Sid": "DescribeForSelfIdentify", "Effect": "Allow",
             "Action": "ec2:DescribeInstances", "Resource": "*"},
        ]
    return {"Version": "2012-10-17", "Statement": st}


if __name__ == "__main__":
    for env in ("prod", "staging"):
        for kind in ("web", "worker"):
            f = OUT / f"transcriber-{env}-{kind}-policy.json"
            f.write_text(json.dumps(build(env, kind), indent=2, ensure_ascii=False) + "\n")
            print("wrote", f.name)
