from collections import Counter
import glob
import itertools
import os
import sys
import logging

from joblib import Parallel, delayed
import pandas as pd
import sourmash
from sourmash.logging import error, notify, set_quiet
from sourmash import sourmash_args


from tqdm import tqdm

logging.basicConfig(filename='sig_utils.log', level=logging.DEBUG)

KSIZES = 21,24,27,30,33,36,39,42,45,48,51,54,57,60,63,66,69,72,75
MOLECULES = 'protein', 'dayhoff'
SCALEDS = 2, 5, 10


SKETCH_INFO_PATTERN = '(?P<mol_or_alpha>molecule|alphabet)-(?P<alphabet>\w+)__ksize-(?P<ksize>\d+)__(?P<sketch_style>num_hashes|scaled)-(?P<sketch_value>\d+)'

SKETCH_PARAMS = ['alphabet', 'ksize', 'sketch_style', 'sketch_value']

CELL_PARAMS = ['channel', 'cell_barcode']
SKETCH_CELL_PARAMS = SKETCH_PARAMS + CELL_PARAMS

def sanitize(name):
    """Make the name able to be a valid path name. 
    
    No spaces or slashes, everything lowercase"""
    return name.lower().replace(' ', '_').replace('/', '-slash-')


def make_sketch_id(alpha, ksize, style, value):
    sketch_id = f'alphabet-{alpha}__ksize-{ksize}__{style}-{value}'
    return sketch_id


def get_sig_file_df(sig_folder, verbose=False, aligned_unaligned_merged=False):
    df = pd.Series(glob.glob(f'{sig_folder}/*.sig'), name='fullpath').to_frame()
    df['basename'] = df['fullpath'].map(os.path.basename)
    if verbose:
        print('df.shape:', df.shape)

    if aligned_unaligned_merged:
        cell_info = pd.Series(df['basename'].str.split('.').str[0], name='cell_id').to_frame()
        sig_info = pd.DataFrame(index=df.index)
    else:
        sig_info = df['basename'].str.extractall(SKETCH_INFO_PATTERN)
        sig_info = sig_info.droplevel(-1)
        sig_info['ksize'] = sig_info['ksize'].astype(int)
        sig_info['sketch_value'] = sig_info['sketch_value'].astype(int)
        cell_info = df['basename'].str.split('__', expand=True)
        cols_to_drop = cell_info.columns.intersection([3,4,5,6,7])
        cell_info = cell_info.drop(cols_to_drop, axis=1)
        cell_info = cell_info.rename(columns={
            0: 'channel', 1: 'alignment_status', 2: 'cell_barcode'})
        cell_info['cell_id'] = cell_info.apply(
            lambda x: "{channel}__{cell_barcode}".format(**x), axis=1)

    
    sigs_with_metadata = pd.concat([df, sig_info, cell_info], axis=1)
    
    # don't worrry about sorting for now
#     sort_cols = sigs_with_metadata.columns.intersection(SKETCH_CELL_PARAMS)
#     if len(sort_cols) > 0:
#         sigs_with_metadata = sigs_with_metadata.sort_values(sort_cols)
    if verbose:
        print('sigs_with_metadata.shape:', sigs_with_metadata.shape)
    return sigs_with_metadata

## -- Sourmash signature stuff --- ###


# from sourmash.sig import _check_abundance_compatibility

def merge(filenames, ksize, moltype, name=None, flatten=False, outsig=None):
    """
    merge one or more signatures.
    
    Adapted from 'sourmash sig merge' command
    """

    first_sig = None
    mh = None
    total_loaded = 0


    for sigfile in filenames:
        this_n = 0
        for sigobj in sourmash.load_signatures(sigfile,
                                                        ksize=ksize,
                                                        select_moltype=moltype):

            # first signature? initialize a bunch of stuff
            if first_sig is None:
                first_sig = sigobj
                mh = first_sig.minhash.copy_and_clear()

            try:
                sigobj_mh = sigobj.minhash

                mh.merge(sigobj_mh)
            except:
                error("ERROR when merging signature '{}' ({}) from file {}",
                      sigobj.name(), sigobj.md5sum()[:8], sigfile)
                raise

            this_n += 1
            total_loaded += 1

    merged_sigobj = sourmash.SourmashSignature(mh)
    if name is not None:
        merged_sigobj._name = name
    
    if outsig is not None:
        with open(outsig, 'wt') as f:
            sourmash.save_signatures([merged_sigobj], fp=f)
    
    return merged_sigobj


def merge_signatures(params, df, outdir_base):
    alpha, ksize, style, value, channel, barcode = params
    
    sketch_id = f'alphabet-{alpha}__ksize-{ksize}__{style}-{value}'
    outdir = f"{outdir_base}/{sketch_id}"
    if not os.path.exists(outdir):
        try:
            os.mkdir(outdir)
        except FileExistsError:
            # Already created by another thread
            pass
    
    cell_id = f'{channel}__{barcode}'
    outsig = f'{outdir}/{cell_id}.sig'
    insigs = ' '.join(df['fullpath'])
    
    try:
        merged_sigobj = merge(df['fullpath'].values, ksize=ksize, moltype=alpha)
    except ValueError:
        print(f'cell: {cell_id} was not able to be merged\n')
        return cell_id, False
    
    # Rename -- set the name to the cell id
    merged_sigobj._name = cell_id
    
    with open(outsig, 'wt') as f:
        sourmash.save_signatures([merged_sigobj], fp=f)
    return cell_id, True
        

def merge_aligned_unaligned_sigs(sig_folder, outdir_base, verbose=False, n_jobs=32):

    sig_df = get_sig_file_df(sig_folder, verbose=verbose)
    if verbose:
        print("sig_df.head()\n", sig_df.head())

    ## Filter for only signatures that have both aligned and unaligned versions
    # Both aligned and unaligned present
    sig_df_both_aligned_unaligned = sig_df.groupby(SKETCH_CELL_PARAMS).filter(lambda x: len(x) == 2)
    if verbose:
        print('--\nsig_df_both_aligned_unaligned.shape:', sig_df_both_aligned_unaligned.shape)
    sig_df_both_aligned_unaligned.head()

    if verbose:
        print("--\nsig_df_both_aligned_unaligned.cell_id.value_counts():\n", sig_df_both_aligned_unaligned.cell_id.value_counts())

    ## Merge signatures from same channel, cell barcode, ksize, molecule, scaled value
    grouped = sig_df_both_aligned_unaligned.groupby(SKETCH_CELL_PARAMS)

    merged_success = Parallel(n_jobs=n_jobs)(delayed(merge_signatures)(params, df, outdir_base=outdir_base) for params, df in tqdm(grouped))
    merged_success = pd.Series(dict(merged_success))
    return merged_success



def _merge_signatures(params, df, outdir_base, ksize=None, moltype=None, style='scaled', value=10, sig_fullpath='sig_fullpath', force=False):
    channel, barcode = params
    
    sketch_id = f'alphabet-{moltype}__ksize-{ksize}__{style}-{value}'
    outdir = f"{outdir_base}/{sketch_id}"
    cell_id = f'{channel}__{barcode}'
    outsig = f'{outdir}/{cell_id}.sig'
    
    if not force and os.path.exists(outsig):
        return cell_id, True
    
    if not os.path.exists(outdir):
        try:
            os.mkdir(outdir)
        except FileExistsError:
            # Already created by another thread
            pass
    
#     insigs = ' '.join(df['sig_fullpath'])
    
    try:
        merged_sigobj = merge(df[sig_fullpath].values, ksize=ksize, moltype=moltype)
    except ValueError:
        print(f'cell: {cell_id} was not able to be merged\n')
        return cell_id, False
    
    # Rename -- set the name to the cell id
    merged_sigobj._name = cell_id
    
    with open(outsig, 'wt') as f:
        sourmash.save_signatures([merged_sigobj], fp=f)
    return cell_id, True
        
    
def _flatten(
    filename, 
    ksize, 
    moltype, 
    cell_id, # to rename 
    md5=None, 
    name=None,
    quiet=True
):
    set_quiet(quiet)

    siglist = [filename]
    outlist = []
    total_loaded = 0
    siglist = list(siglist)
    #raise ValueError
    total_loaded += len(siglist)

    # select!
    if md5 is not None:
        siglist = [ ss for ss in siglist if md5 in ss.md5sum ]
        
    if name is not None:
        siglist = [ ss for ss in siglist if name in ss.name ]

    for ss in siglist:
        flattened_mh = ss.minhash.copy_and_clear()
        flattened_mh.track_abundance = False
        flattened_mh.add_many(ss.minhash.get_mins())

        ss.minhash = flattened_mh
    
    outlist.extend(siglist)
    flattened = sourmash.save_signatures(outlist)
    
    flattened = sourmash.load_one_signature(
        flattened,
        ksize=ksize,
        select_moltype=moltype
    )
    flattened._name = cell_id
    
    return flattened


def _subtract(
    original_sig, 
    subtracted_sig_path, 
    ksize, 
    cell_id,
    moltype="dayhoff",
    quiet=True
):
    """
    subtract one or more signatures from another
    """
    set_quiet(quiet)
    from_sigobj = original_sig

    from_mh = from_sigobj.minhash
    subtract_mins = set(from_mh.hashes)

    total_loaded = 0

    for sigobj in sourmash_args.load_file_as_signatures(
        subtracted_sig_path,
        ksize=ksize,
        select_moltype=moltype
    ):
        if not sigobj.minhash.is_compatible(from_mh):
            logging.debug("incompatible minhashes; specify -k and/or molecule type.")
            return

        subtract_mins -= set(sigobj.minhash.hashes)

        logging.info('loaded and subtracted signatures from {}...'.format(sigobj.name))
        total_loaded += 1

    if not total_loaded:
        logging.debug(f"no signatures to subtract from {original_sig} {subtracted_sig_path}t!?")
        return

    subtract_mh = from_sigobj.minhash.copy_and_clear()
    subtract_mh.add_many(subtract_mins)

    subtract_sigobj = sourmash.SourmashSignature(subtract_mh)
    subtract_sigobj._name = cell_id
    
    return subtract_sigobj


def _intersect(
    ksize,  
    signatures_to_merge: list, 
    abund_sig,
    cell_id, # to rename 
    moltype="dayhoff",
    quiet=True
):
    """
    intersect one or more signatures by taking the intersection of hashes.
    This function always removes abundances.
    """
    set_quiet(quiet)

    first_sig = None
    mins = None
    total_loaded = 0

    for sigobj in signatures_to_merge:
        if first_sig is None:
            first_sig = sigobj
            mins = set(sigobj.minhash.hashes)
        else:
            
            # check signature compatibility --
            if not sigobj.minhash.is_compatible(first_sig.minhash):
                raise ValueError("incompatible minhashes; specify -k and/or molecule type.")

        mins.intersection_update(sigobj.minhash.hashes)
        total_loaded += 1
        logging.debug(f'loaded and intersected signatures from {sigobj.name}...')

    if total_loaded == 0:
        raise ValueError("no signatures to merge!?")

    if not abund_sig.minhash.track_abundance:
        logging.debug(f" abundances not set for: ksize {ksize} and cell_id {cell_id}")
        pass
        #raise ValueError("--track-abundance not set on loaded signature?! exiting.")
    else:
        intersect_mh = abund_sig.minhash.copy_and_clear()
        abund_mins = abund_sig.minhash.hashes

        # do one last intersection
        mins.intersection_update(abund_mins)
        abund_mins = { k: abund_mins[k] for k in mins }

        intersect_mh.set_abundances(abund_mins)
        intersect_sigobj = sourmash.SourmashSignature(intersect_mh)
        intersect_sigobj._name = cell_id
        logging.debug(f" intersect passed for: ksize {ksize}, cell_id {cell_id}")
        return intersect_sigobj


def parallel_merge_aligned_unaligned_sigs(
    sig_df, 
    outdir_base, 
    groupby=['channel', 'cell_barcode'], 
    verbose=False, 
    n_jobs=32, 
    ksizes=KSIZES, 
    moltype='dayhoff', 
    sig_fullpath='sig_fullpath',
    force=False
):

    ## Merge signatures from same channel, cell barcode, ksize, molecule, scaled value
    grouped = sig_df.groupby(groupby)
    n_iter = len(grouped) * len(ksizes)
    print(f"total number of iterations: {n_iter}")

    merged_success = Parallel(n_jobs=n_jobs)(
        delayed(_merge_signatures)(
            params, df, outdir_base=outdir_base, ksize=ksize, moltype=moltype, sig_fullpath=sig_fullpath
        ) 
        for (params, df), ksize in tqdm(itertools.product(grouped, ksizes), total=n_iter))
    merged_success = pd.Series(dict(merged_success))
    return merged_success


def get_hashes_to_remove(sigs, percent_threshold):
    shared_hashes = Counter()
    for sig in tqdm(sigs):
        shared_hashes.update(sig.minhash.hashes)
        
    n_sigs_threshold = percent_threshold * len(sigs)
    hashes_to_remove = set([x for x, count in shared_hashes.items() if count >= n_sigs_threshold])
    return hashes_to_remove


def remove_hashes(sig, hashes_to_remove):
    subtract_mh = sig.minhash.copy_and_clear()
    hash_dict = sig.minhash.hashes
    hashes_to_keep = set(hash_dict.keys()) - hashes_to_remove
    subtract_mh.add_many(hashes_to_keep)
    subtract_mh.set_abundances(
        {h: hash_dict[h] for h in hashes_to_keep}
    )
    subtract_sigobj = sourmash.SourmashSignature(
        subtract_mh, 
        name=sig.name()
    )
    return subtract_sigobj
    
def remove_common_hashes(sigs, percent_threshold):
    hashes_to_remove = get_hashes_to_remove(sigs, percent_threshold)
    subtracted_sigs = [remove_hashes(sig, hashes_to_remove) for sig in sigs]

    return subtracted_sigs

def load_sigfiles(sigfiles, ksize, moltype):
    sigs = []
    for filename in sigfiles:
        sigs.extend(sourmash.load_file_as_signatures(filename, ksize=ksize, select_moltype=moltype))
    return sigs


def remove_common_hashes_from_sig_df(
    sig_df, sketch_id, ksize, moltype, fraction_threshold=0.8, sig_col='sig_path', output_dir=None
):
    """
    Remove hashes that are present in `fraction_threshold` of all signatures, e.g in 80% or more of signatures
    
    output_dir : str, optional
        If set, then write the signatures to {output_dir}/{sketch_id}/{sig_df[sig_col].map.os.path(basename)}.sig
    """
    sigs = load_sigfiles(sig_df[sig_col].values, ksize, moltype)
    sigs_without_common_hashes = remove_common_hashes(sigs, fraction_threshold)
    series = pd.Series(
        sigs_without_common_hashes,
        index=[sig.name() for sig in sigs]
    )
    if output_dir:
        basenames = sig_df[sig_col].map(os.path.basename)
        sketch_dir = os.path.join(output_dir, sketch_id)
        if not os.path.exists(sketch_dir):
            try:
                os.makedirs(sketch_dir)
            except FileExistsError:
                # Some other thread made this
                pass
            
        for subtracted_sig, basename in zip(sigs_without_common_hashes, basenames):
            outfile = os.path.join(sketch_dir, basename + '.sig')
            with open(outfile, 'wt') as f:
                sourmash.save_signatures([subtracted_sig], fp=f)
            
    return sigs_without_common_hashes
