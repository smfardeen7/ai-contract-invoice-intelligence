"""Optional learned line tagger; an experiment, not the default extractor.

Input CSV columns document_id,text,label. All lines from a document stay in
one split. Only train-split text enters the vocabulary. Requires optional ML deps.
"""
import argparse
import json
from pathlib import Path


def main():
    import numpy as np
    import pandas as pd
    import tensorflow as tf
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.metrics import classification_report
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path, default=Path("models/line-tagger.keras"))
    parser.add_argument("--epochs", type=int, default=10)
    args = parser.parse_args()
    df = pd.read_csv(args.csv, dtype=str)
    if not {"document_id", "text", "label"} <= set(df) or df.isna().any().any():
        parser.error("Expected non-null document_id,text,label columns")
    labels = sorted(df.label.unique().tolist())
    if len(labels) < 2 or df.document_id.nunique() < 5:
        parser.error("Need at least two labels and five independent documents")
    train, test = next(GroupShuffleSplit(n_splits=1, test_size=.25, random_state=42).split(df, groups=df.document_id))
    if set(df.iloc[train].label) != set(labels):
        parser.error("Training split is missing labels; supply more independent documents")
    tf.keras.utils.set_random_seed(42)
    vectorizer = tf.keras.layers.TextVectorization(max_tokens=10000, output_mode="tf_idf")
    train_text = tf.constant(df.iloc[train].text.tolist())
    test_text = tf.constant(df.iloc[test].text.tolist())
    vectorizer.adapt(train_text)
    model = tf.keras.Sequential([tf.keras.Input(shape=(), dtype=tf.string), vectorizer,
        tf.keras.layers.Dense(64, activation="relu"), tf.keras.layers.Dropout(.2),
        tf.keras.layers.Dense(len(labels), activation="softmax")])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    y = np.array([labels.index(x) for x in df.label], dtype=np.int32)
    model.fit(train_text, y[train], epochs=args.epochs, batch_size=32, verbose=0)
    predicted = model.predict(test_text, verbose=0).argmax(axis=1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model.save(args.output)
    report = {"labels": labels, "train_documents": df.iloc[train].document_id.nunique(),
              "test_documents": df.iloc[test].document_id.nunique(),
              "report": classification_report(y[test], predicted, labels=list(range(len(labels))), target_names=labels, output_dict=True, zero_division=0),
              "purpose": "Line-label research experiment; not field extraction accuracy"}
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
