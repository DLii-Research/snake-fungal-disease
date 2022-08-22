# deep-learning-dna

A repository of deep learning models for DNA samples and sequences.

## Model Types

### DNA Embeddings

- DNABERT
- DNABERT Autoencoder

### GAN

- Conditional GAN
- Conditional WGAN
- Conditional VEEGAN
- Conditional VEEWGAN
- Generative Adversarial Set Transformers (GAST)

- DNAGAST
- DNAWGAST
- DNAVEEGAST
- DNAVEEWGAST

## Dependencies

In order to run these models, you'll need to install the necessary dependencies from my other repositories linked below.

- [LMDBM (modified)](https://github.com/SirDavidLudwig/lmdb-python-dbm)
- [Tensorflow](https://www.tensorflow.org/)
- [tf-utilities](https://pypi.org/project/tf-utilities/)
- [tf-settransformer](https://pypi.org/project/tf-settransformer/)
- [Weights & Biases](https://wandb.ai)

## Training & Evaluation

Each model architecture can me trained/evaluated by invoking the appropriate script located in the `scripts/` directory. These scripts integrate the Weights & Biases platform directly for easy version control, thus W&B must be configured appropriately on your system before execution.
