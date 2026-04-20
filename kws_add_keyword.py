"""工具脚本：将中文/英文唤醒词文本转换为 token 序列并追加到 keywords.txt"""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="添加 KWS 唤醒词到 keywords.txt")
    parser.add_argument("keyword", help="唤醒词文本，如: 你好小助手")
    parser.add_argument(
        "--tokens",
        default="sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/tokens.txt",
    )
    parser.add_argument("--output", default="keywords.txt")
    parser.add_argument("--score", type=float, default=None, help="Boost score")
    parser.add_argument(
        "--threshold", type=float, default=None, help="Detection threshold"
    )
    args = parser.parse_args()

    import sherpa_onnx

    result = sherpa_onnx.text2token(
        [args.keyword], tokens=args.tokens, tokens_type="ppinyin"
    )
    if not result or not result[0]:
        print("错误: 未生成 token 序列", file=sys.stderr)
        sys.exit(1)

    tokens_str = " ".join(result[0])

    # 追加可选的 score/threshold 元数据
    suffix = ""
    if args.score is not None:
        suffix += f" :{args.score}"
    if args.threshold is not None:
        suffix += f" #{args.threshold}"

    line = f"{tokens_str}{suffix} @{args.keyword}"

    with open(args.output, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"已添加: {line}")


if __name__ == "__main__":
    main()
