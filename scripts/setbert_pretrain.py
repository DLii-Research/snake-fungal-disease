from dnadb import fasta, fastq, sample
from itertools import chain
from pathlib import Path
import sys
import tensorflow as tf
import tf_utilities.scripting as tfs
from tf_utilities.utils import str_to_bool

import bootstrap

from deepdna.data.dataset import Dataset
from deepdna.nn import losses
from deepdna.nn.callbacks import LearningRateStepScheduler
from deepdna.nn.data_generators import SequenceGenerator
from deepdna.nn.models import dnabert, setbert, load_model
from deepdna.nn.utils import optimizer

def define_arguments(cli: tfs.CliArgumentFactory):
    # General config
    cli.use_wandb()
    cli.use_strategy()
    cli.use_rng()

    # DNABERT pretrained model artifact
    cli.artifact("--dnabert", required=True)

    # Dataset path
    cli.argument("dataset_paths", type=str, nargs='+')

    # Architecture Settings
    cli.argument("--subsample-size", type=int, default=1000)
    cli.argument("--embed-dim", type=int, default=64)
    cli.argument("--stack", type=int, default=8)
    cli.argument("--num-heads", type=int, default=8)
    cli.argument("--num-induce-points", type=int, default=64)
    cli.argument("--pre-layernorm", type=str_to_bool, default=True)

    # Training settings
    cli.use_training(epochs=2000, batch_size=16)
    cli.argument("--batches-per-epoch", type=int, default=100)
    cli.argument("--val-batches-per-epoch", type=int, default=16)
    cli.argument("--mask-ratio", type=float, default=0.15)
    cli.argument("--optimizer", type=str, default="adam")
    cli.argument("--lr", type=float, default=4e-4)
    cli.argument("--init-lr", type=float, default=0.0)
    cli.argument("--warmup-steps", type=int, default=None)
    cli.argument("--loss-fn", choices=["chamfer", "setloss"], default="setloss")

    # Logging
    cli.argument("--save-to", type=str, default=None)
    cli.argument("--log-artifact", type=str, default=None)


def load_pretrained_dnabert_model(config) -> dnabert.DnaBertModel:
    pretrain_path = tfs.artifact(config, "dnabert")
    return load_model(pretrain_path, dnabert.DnaBertPretrainModel).base


def load_fasta(path):
    print(path)


def load_datasets(config, dnabert_base: dnabert.DnaBertModel) -> tuple[SequenceGenerator, SequenceGenerator|None]:
    datasets = [Dataset(path) for path in config.dataset_paths]
    test_datasets = [d for d in datasets if d.has_split(Dataset.Split.Test)]

    train_samples = []
    train_fastas = [f for d in datasets for f in d.fasta_dbs(Dataset.Split.Train)]
    for fasta_db in train_fastas:
        if fasta_db.with_suffix(".mapping.db").exists():
            train_samples += sample.load_multiplexed_fasta(fasta_db, fasta_db.with_suffix(".mapping.db"))
        else:
            train_samples.append(fasta.load_fasta(fasta_db))
    train_samples += [f for d in datasets for f in map(fastq.FastqDb, d.fastq_dbs(Dataset.Split.Train))]

    print("Found", len(train_samples), "sample(s).")

    generator_args = dict(
        sequence_length=dnabert_base.sequence_length,
        kmer=dnabert_base.kmer,
        use_kmer_inputs=True,
        use_kmer_labels=True,
        batch_size = config.batch_size,
        subsample_size = config.subsample_size,
    )

    train = SequenceGenerator(
        train_samples,
        batches_per_epoch=config.batches_per_epoch,
        rng = tfs.rng(),
        **generator_args
    )

    validation = None

    # Weak validation
    validation = SequenceGenerator(
        train_samples,
        batches_per_epoch=config.val_batches_per_epoch,
        rng = tfs.rng(),
        shuffle=False,
        **generator_args,
    )

    # Strong validation
    # if len(test_datasets):
    #     test_samples = []
    #     test_fastas = [f for d in datasets for f in d.fasta_dbs(Dataset.Split.Test)]
    #     for fasta_db in test_fastas:
    #         if fasta_db.with_suffix(".mapping.db").exists():
    #             test_samples += sample.load_multiplexed_fasta(fasta_db, fasta_db.with_suffix(".mapping.db"))
    #         else:
    #             test_samples.append(fasta.load_fasta(fasta_db))
    #     test_samples += [f for d in datasets for f in map(fastq.FastqDb, d.fastq_dbs(Dataset.Split.Test))]
    #     validation = SequenceGenerator(
    #         test_samples,
    #         batches_per_epoch=config.val_batches_per_epoch,
    #         rng = tfs.rng(),
    #         **generator_args
    #     )
    return (train, validation)


def create_model(config, dnabert_base: dnabert.DnaBertModel):
    print("Creating model...")
    encoder = dnabert.DnaBertEncoderModel(dnabert_base, chunk_size=256)
    base = setbert.SetBertModel(
        encoder,
        embed_dim=config.embed_dim,
        max_set_len=config.subsample_size,
        stack=config.stack,
        num_heads=config.num_heads,
        pre_layernorm=config.pre_layernorm)
    model = setbert.SetBertPretrainModel(
        base=base,
        mask_ratio=config.mask_ratio)

    match config.loss_fn:
        case "chamfer":
            loss_fn = losses.chamfer_distance
        case "setloss":
            loss_fn = losses.SortedLoss()
        case _:
            raise ValueError(f"Unknown loss function: {config.loss_fn}")

    model.compile(
        optimizer=optimizer(config.optimizer, learning_rate=config.lr),
        loss=loss_fn,
        run_eagerly=config.run_eagerly
    )
    return model


def load_previous_model(path: str|Path) -> setbert.SetBertPretrainModel:
    print("Loading model from previous run:", path)
    return load_model(path)


def create_callbacks(config):
    print("Creating callbacks...")
    callbacks = [tf.keras.callbacks.ModelCheckpoint(
        tfs.path_to(config.save_to)
    )]
    if tfs.is_using_wandb():
        callbacks.append(tfs.wandb_callback(save_model=False))
    if config.warmup_steps is not None:
        callbacks.append(LearningRateStepScheduler(
            init_lr = config.init_lr,
            max_lr=config.lr,
            warmup_steps=config.warmup_steps,
            end_steps=config.batches_per_epoch*config.epochs
        ))
    return callbacks


def train(config, model_path):
    with tfs.strategy(config).scope(): # type: ignore

        # Load the pretrained DNABERT model
        dnabert_base = load_pretrained_dnabert_model(config)

        # Load the dataset
        train_data, val_data = load_datasets(config, dnabert_base)

        # Create the autoencoder model
        if model_path is not None:
            model = load_model(model_path)
        else:
            model = create_model(config, dnabert_base)

        # Create any collbacks we may need
        callbacks = create_callbacks(config)

        # Train the model with keyboard-interrupt protection
        tfs.run_safely(
            model.fit,
            train_data,
            validation_data=val_data,
            subbatch_size=config.sub_batch_size,
            initial_epoch=tfs.initial_epoch(config),
            epochs=config.epochs,
            callbacks=callbacks,
            use_multiprocessing=(config.data_workers > 1),
            workers=config.data_workers)

        # Save the model
        if config.save_to:
            model.save(tfs.path_to(config.save_to))

    return model


def main(argv):
    config = tfs.init(define_arguments, argv[1:])

    # Set the random seed
    tfs.random_seed(config.seed)

    # If this is a resumed run, we need to fetch the latest model run
    model_path = None
    if tfs.is_resumed():
        print("Restoring previous model...")
        model_path = tfs.restore_dir(config.save_to)

    print(config)

    # Train the model if necessary
    if tfs.initial_epoch(config) < config.epochs:
        train(config, model_path)
    else:
        print("Skipping training")

    # Upload an artifact of the model if requested
    if config.log_artifact:
        print("Logging artifact to", config.save_to)
        assert bool(config.save_to)
        tfs.log_artifact(config.log_artifact, [
            tfs.path_to(config.save_to)
        ], type="model")


if __name__ == "__main__":
    sys.exit(tfs.boot(main, sys.argv))
