import argparse
from pprint import pprint

from datasets import load_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe ArabicRAGB dataset schema.")
    parser.add_argument(
        "--dataset",
        default="HeshamHaroon/ArabicRAGB",
        help="HuggingFace dataset path.",
    )
    parser.add_argument(
        "--split",
        default=None,
        help="Dataset split to inspect (defaults to the first available split).",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=2,
        help="Number of samples to print.",
    )
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    splits = list(dataset.keys())
    print("Available splits:", splits)
    split_name = args.split or (splits[0] if splits else None)
    if not split_name:
        raise SystemExit("No splits found in the dataset.")

    split = dataset[split_name]
    print(f"Selected split: {split_name}")
    print("Features:")
    pprint(split.features)

    print("\nSample rows:")
    for idx in range(min(args.samples, len(split))):
        row = split[idx]
        print(f"\n--- Sample {idx} ---")
        pprint(row)


if __name__ == "__main__":
    main()
