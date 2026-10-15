"""
End-to-End CNN Training Pipeline
Refactored for production deployment, modularity, and clean artifact generation.
"""

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import classification_report, confusion_matrix
from tensorflow.keras.applications import Xception
from tensorflow.keras.applications.xception import preprocess_input
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from tensorflow.keras.layers import BatchNormalization, Dense, Dropout, GlobalAveragePooling2D
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.regularizers import l2


# ==========================================
# 1. Configuration Management
# ==========================================
@dataclass
class PipelineConfig:
    """Centralized configuration for the training pipeline."""

    # Paths
    source_dir: str
    artifacts_dir: str = "artifacts"

    # Image Parameters
    height: int = 300
    width: int = 400
    batch_size: int = 16

    # Training Parameters
    phase1_epochs: int = 30
    phase1_lr: float = 1e-3
    phase2_epochs: int = 30
    phase2_lr: float = 1e-5
    unfreeze_from_layer: int = -30
    validation_split: float = 0.20
    random_seed: int = 23456


def parse_args() -> PipelineConfig:
    """Parses CLI arguments to override dataclass defaults."""
    parser = argparse.ArgumentParser(description="Run the CNN Image Classification Pipeline.")
    parser.add_argument("--source_dir", type=str, required=True, help="Path to raw image dataset.")
    parser.add_argument("--batch_size", type=int, default=16, help="Batch size for training.")
    parser.add_argument("--epochs", type=int, default=30, help="Base epochs per phase.")

    args = parser.parse_args()
    return PipelineConfig(
        source_dir=args.source_dir,
        batch_size=args.batch_size,
        phase1_epochs=args.epochs,
        phase2_epochs=args.epochs,
    )


def setup_environment(config: PipelineConfig) -> dict[str, Path]:
    """Creates the structured artifact directories and initializes logging."""
    base_dir = Path(config.artifacts_dir)
    dirs = {
        "model": base_dir / "model",
        "logs": base_dir / "logs",
        "metadata": base_dir / "metadata",
        "reports": base_dir / "reports",
        "plots": base_dir / "plots",
    }

    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(dirs["logs"] / "training.log"), logging.StreamHandler()],
    )
    return dirs


# ==========================================
# 2. Data Pipeline
# ==========================================
def create_data_generators(config: PipelineConfig) -> tuple[ImageDataGenerator, ImageDataGenerator]:
    """Constructs Keras data generators with built-in validation splitting."""
    logging.info("Initializing data generators...")

    train_datagen = ImageDataGenerator(
        preprocessing_function=preprocess_input,
        validation_split=config.validation_split,
        rotation_range=20,
        horizontal_flip=True,
        width_shift_range=0.1,
        height_shift_range=0.1,
        zoom_range=0.1,
    )

    test_datagen = ImageDataGenerator(
        preprocessing_function=preprocess_input,
        validation_split=config.validation_split,
    )

    train_gen = train_datagen.flow_from_directory(
        config.source_dir,
        target_size=(config.height, config.width),
        batch_size=config.batch_size,
        class_mode="categorical",
        subset="training",
        seed=config.random_seed,
    )

    val_gen = test_datagen.flow_from_directory(
        config.source_dir,
        target_size=(config.height, config.width),
        batch_size=config.batch_size,
        class_mode="categorical",
        subset="validation",
        shuffle=False,  # Critical: Must not shuffle validation data for accurate metrics
    )

    return train_gen, val_gen


# ==========================================
# 3. Model Architecture & Compilation
# ==========================================
def build_model(num_classes: int, config: PipelineConfig) -> Model:
    """Constructs the Xception backbone with a custom classification head."""
    logging.info("Building Xception model architecture...")

    base_model = Xception(
        weights="imagenet",
        include_top=False,
        input_shape=(config.height, config.width, 3),
    )

    # Freeze the backbone
    for layer in base_model.layers:
        layer.trainable = False

    x = base_model.output
    x = GlobalAveragePooling2D()(x)
    x = BatchNormalization()(x)
    x = Dense(256, activation="relu", kernel_regularizer=l2(1e-4))(x)
    x = Dropout(0.4)(x)
    outputs = Dense(num_classes, activation="softmax")(x)

    return Model(inputs=base_model.input, outputs=outputs)


# ==========================================
# 4. Training Orchestration
# ==========================================
def train_model(model: Model, train_gen, val_gen, config: PipelineConfig) -> dict:
    """Executes the two-phase training process and collects history."""

    callbacks = [
        EarlyStopping(monitor="val_loss", patience=8, restore_best_weights=True, verbose=1),
        ReduceLROnPlateau(monitor="val_loss", factor=0.3, patience=3, min_lr=1e-7, verbose=1),
    ]

    full_history = {}

    # --- Phase 1: Train Head ---
    logging.info("Starting Phase 1: Training Classification Head")
    model.compile(
        optimizer=Adam(learning_rate=config.phase1_lr),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )

    history_p1 = model.fit(
        train_gen, validation_data=val_gen, epochs=config.phase1_epochs, callbacks=callbacks
    )
    full_history["phase1"] = history_p1.history

    # --- Phase 2: Fine-Tuning ---
    logging.info("Starting Phase 2: Fine-Tuning Top Layers")
    for layer in model.layers[config.unfreeze_from_layer :]:
        layer.trainable = True

    model.compile(
        optimizer=Adam(learning_rate=config.phase2_lr),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )

    history_p2 = model.fit(
        train_gen, validation_data=val_gen, epochs=config.phase2_epochs, callbacks=callbacks
    )
    full_history["phase2"] = history_p2.history

    return full_history


# ==========================================
# 5. Evaluation & Artifact Generation
# ==========================================
def save_metadata(train_gen, out_dirs: dict[str, Path]):
    """Saves both the human-readable text file and the machine-readable JSON."""
    idx_to_class = {v: k for k, v in train_gen.class_indices.items()}
    class_names = [idx_to_class[i] for i in range(len(idx_to_class))]

    # 1. Human-Readable TXT
    txt_path = out_dirs["metadata"] / "class_names.txt"
    with open(txt_path, "w") as f:
        for name in class_names:
            f.write(f"{name}\n")

    # 2. Machine-Readable JSON (Crucial for downstream pipelines)
    json_path = out_dirs["metadata"] / "class_mapping.json"
    with open(json_path, "w") as f:
        json.dump(idx_to_class, f, indent=4)

    logging.info(f"Metadata saved to {out_dirs['metadata']}")
    return class_names


def generate_evaluation_artifacts(
    model: Model, val_gen, class_names: list, out_dirs: dict[str, Path], history: dict
):
    """Generates and saves the classification CSV, confusion matrix, and plots."""
    logging.info("Generating evaluation artifacts...")

    # Predictions
    val_gen.reset()
    y_prob = model.predict(val_gen, steps=int(np.ceil(val_gen.samples / val_gen.batch_size)))
    y_pred = np.argmax(y_prob, axis=1)
    y_true = val_gen.classes

    # 1. Classification Report (CSV)
    report_dict = classification_report(y_true, y_pred, target_names=class_names, output_dict=True)
    report_df = pd.DataFrame(report_dict).transpose()

    csv_path = out_dirs["reports"] / "classification_report.csv"
    report_df.to_csv(csv_path, index=True)
    logging.info(f"Classification report saved to {csv_path}")

    # 2. Confusion Matrix Plot
    cm = confusion_matrix(y_true, y_pred)
    plt.figure(figsize=(10, 8))
    sns.heatmap(
        cm, annot=True, fmt="d", cmap="Blues", xticklabels=class_names, yticklabels=class_names
    )
    plt.title("Confusion Matrix")
    plt.ylabel("Actual Label")
    plt.xlabel("Predicted Label")
    plt.tight_layout()
    plt.savefig(out_dirs["plots"] / "confusion_matrix.png", dpi=300)
    plt.close()

    # 3. Training History Plot
    plt.figure(figsize=(12, 5))

    # Merge histories for plotting
    acc = history["phase1"].get("accuracy", []) + history["phase2"].get("accuracy", [])
    val_acc = history["phase1"].get("val_accuracy", []) + history["phase2"].get("val_accuracy", [])
    loss = history["phase1"].get("loss", []) + history["phase2"].get("loss", [])
    val_loss = history["phase1"].get("val_loss", []) + history["phase2"].get("val_loss", [])

    plt.subplot(1, 2, 1)
    plt.plot(acc, label="Train Accuracy")
    plt.plot(val_acc, label="Validation Accuracy")
    plt.legend()
    plt.title("Model Accuracy")

    plt.subplot(1, 2, 2)
    plt.plot(loss, label="Train Loss")
    plt.plot(val_loss, label="Validation Loss")
    plt.legend()
    plt.title("Model Loss")

    plt.tight_layout()
    plt.savefig(out_dirs["plots"] / "training_history.png", dpi=300)
    plt.close()


# ==========================================
# 6. Main Orchestrator
# ==========================================
def main():
    # 1. Setup
    config = parse_args()
    out_dirs = setup_environment(config)
    logging.info("Pipeline initialized.")

    # 2. Data Load
    train_gen, val_gen = create_data_generators(config)
    num_classes = len(train_gen.class_indices)

    # 3. Metadata
    class_names = save_metadata(train_gen, out_dirs)

    # 4. Model Build & Train
    model = build_model(num_classes, config)
    history = train_model(model, train_gen, val_gen, config)

    # 5. Save Final Model (Weights are restored to best via EarlyStopping)
    model_path = out_dirs["model"] / "final_model.keras"
    model.save(model_path)
    logging.info(f"Production model saved to {model_path}")

    # 6. Evaluate & Artifacts
    generate_evaluation_artifacts(model, val_gen, class_names, out_dirs, history)
    logging.info("Pipeline execution completed successfully.")


if __name__ == "__main__":
    main()
