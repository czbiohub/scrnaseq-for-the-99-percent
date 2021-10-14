import os

FIGURE_FOLDER = os.path.join("..", "figures")
DATA_FOLDER = os.path.join("..", "kmer-homology-data")

# Raw data = straight from the sequencer, or downloaded from a database
RAWDATA_FOLDER = os.path.join(DATA_FOLDER, "00--rawdata")

# Quest for Orthologs 2019 folder
QFO_FOLDER = os.path.join(RAWDATA_FOLDER, "quest-for-orthologs", "2019")

# Quest for Orthologs 2019 Eukaryota data
QFO_EUKARYOTA_FOLDER = os.path.join(
    RAWDATA_FOLDER, "quest-for-orthologs", "2019", "Eukaryota"
)

# BUSCO Mammalia folder
BUSCO_MAMMALIA_FOLDER = os.path.join(RAWDATA_FOLDER, "busco", "mammalia_odb10", "info")


# Processed data = data that has been maniuplated in some way from the raw data
PROCESSED_DATA_FOLDER = os.path.join(DATA_FOLDER, "01--processed-data")

# Data related to orpheum benchmarking
ORPHEUM_BENCHMARKING_FOLDER = os.path.join(
    PROCESSED_DATA_FOLDER, "orpheum-benchmarking"
)
MAMMALIA_BUSCO_SUBSET_FOLDER = os.path.join(
    ORPHEUM_BENCHMARKING_FOLDER, "mammalia_busco_subsets"
)
