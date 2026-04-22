"""工具脚本：将中文/英文唤醒词文本转换为 token 序列并追加到 keywords.txt

核心转换函数 text_to_kws_line() 可被 Web API 等外部模块复用。
"""
import argparse
import sys


def text_to_kws_line(keyword: str, tokens_path: str) -> str:
    """将唤醒词文本转换为 keywords.txt 格式的行。

    Args:
        keyword: 唤醒词文本，如 "你好小助手"
        tokens_path: sherpa-onnx tokens.txt 文件路径

    Returns:
        keywords.txt 格式行，如 "n ǐ h ǎo x iǎo zh ù sh ǒu @你好小助手"

    Raises:
        ValueError: 无法生成 token 序列
        FileNotFoundError: tokens.txt 不存在
    """
    import sherpa_onnx

    result = sherpa_onnx.text2token(
        [keyword], tokens=tokens_path, tokens_type="ppinyin"
    )
    if not result or not result[0]:
        raise ValueError(f"无法为 '{keyword}' 生成拼音 token 序列")

    tokens_str = " ".join(result[0])
    return f"{tokens_str} @{keyword}"


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

    try:
        line = text_to_kws_line(args.keyword, args.tokens)
    except (ValueError, FileNotFoundError) as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 追加可选的 score/threshold 元数据
    if args.score is not None:
        # 插入到 @keyword 之前
        at_idx = line.rfind(" @")
        line = f"{line[:at_idx]} :{args.score}{line[at_idx:]}"
    if args.threshold is not None:
        at_idx = line.rfind(" @")
        line = f"{line[:at_idx]} #{args.threshold}{line[at_idx:]}"

    with open(args.output, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"已添加: {line}")


if __name__ == "__main__":
    main()
