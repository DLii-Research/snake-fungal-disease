#!/bin/bash
#SBATCH --signal=INT@600

if [ -z "${deepdna_env_loaded}" ]; then
    echo "deepdna environment not loaded. Please run 'source env.sh' first."
    exit 1
fi

${python_prefix} ${python_tf} ./scripts/finetuning/dnabert_finetune_taxonomy_bertax.py \
    --wandb-name dnabert-taxonomy-bertax-silva-64d-150l \
    --wandb-project taxonomy-classification \
    --dnabert-pretrain-artifact $dnabert_pretrain_silva \
    --sequences-fasta-db $datasets_path/Synthetic/Synthetic.fasta.db \
    --taxonomy-tsv-db $datasets_path/Synthetic/Synthetic.tax.tsv.db \
    --rank-depth 6 \
    $@
