import csv
import importlib.util
import json
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("tensorflow") is None, reason="Optional TensorFlow environment")
def test_tagger_training_saves_reloadable_model(tmp_path, monkeypatch):
    from invoice_intelligence.train_tagger import main
    import tensorflow as tf
    dataset = tmp_path / "lines.csv"
    with dataset.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["document_id", "text", "label"])
        for document in range(20):
            writer.writerow([f"demo-{document}", f"Invoice: INV-{document}", "invoice_id"])
            writer.writerow([f"demo-{document}", f"Total: {document + 100}.00", "total"])
    model_path = tmp_path / "tagger.keras"
    monkeypatch.setattr(sys, "argv", ["tagger", str(dataset), "--output", str(model_path), "--epochs", "1"])
    main()
    report = json.loads(model_path.with_suffix(".json").read_text())
    assert report["train_documents"] == 15
    assert report["test_documents"] == 5
    model = tf.keras.models.load_model(model_path)
    output = model(tf.constant(["Invoice: INV-101"]))
    assert output.shape == (1, 2)
    assert float(tf.reduce_sum(output)) == pytest.approx(1)
