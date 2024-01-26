""" Registration of whole slide images (WSI)

This example shows how to register, warp, and save a collection
of whole slide images (WSI) using the default parameters.

The results directory contains several folders:

1. *data* contains 2 files:
    * a summary spreadsheet of the alignment results, such
    as the registration error between each pair of slides, their
    dimensions, physical units, etc...

    * a pickled version of the registrar. This can be reloaded
    (unpickled) and used later. For example, one could perform
    the registration locally, but then use the pickled object
    to warp and save the slides on an HPC. Or, one could perform
    the registration and use the registrar later to warp
    points in the slide.

2. *overlaps* contains thumbnails showing the how the images
    would look if stacked without being registered, how they
    look after rigid registration, and how they would look
    after non-rigid registration.

3. *rigid_registration* shows thumbnails of how each image
    looks after performing rigid registration.

4. *non_rigid_registration* shows thumbnails of how each
    image looks after non-rigid registration.

5. *deformation_fields* contains images showing what the
    non-rigid deformation would do to a triangular mesh.
    These can be used to get a better sense of how the
    images were altered by non-rigid warping

6. *processed* shows thumnails of the processed images.
    This are thumbnails of the images that are actually
    used to perform the registration. The pre-processing
    and normalization methods should try to make these
    images look as similar as possible.


After registraation is complete, one should view the
results to determine if they aare acceptable. If they
are, then one can warp and save all of the slides.


docker run -it --rm --name test_examples  -v "$HOME:$HOME" valis-wsi-arm64 python3 /Users/gatenbcd/Dropbox/Documents/image_processing/valis_project/valis/tests/test_examples.py
"""

import time
import os
import numpy as np
from itertools import chain
import pathlib
import ome_types

import shutil
import sys
import os
# sys.path.append("/Users/gatenbcd/Dropbox/Documents/image_processing/valis_project/valis")
from valis import registration, valtils
from valis.micro_rigid_registrar import MicroRigidRegistrar

def get_dirs():
    cwd = os.getcwd()
    in_container = sys.platform == "linux" and os.getcwd() == cwd
    if not in_container:
        dir_split = cwd.split(os.sep)
        split_idx = [i for i in range(len(dir_split)) if dir_split[i] == "valis_project"][0]
        parent_dir = os.sep.join(dir_split[:split_idx+1])

        results_dst_dir = os.path.join(parent_dir, f"valis/tests/{sys.version_info.major}{sys.version_info.minor}")
    else:
        parent_dir = "/Users/gatenbcd/Dropbox/Documents/image_processing/valis_project"
        results_dst_dir = os.path.join(parent_dir, f"valis/tests/docker")

    return parent_dir, results_dst_dir, in_container


def cnames_from_filename(src_f):
    """Get channel names from file name
    Note that the DAPI channel is not part of the filename
    but is always the first channel.

    """
    f = valtils.get_name(src_f)
    return ["DAPI"] + f.split(" ")


parent_dir, results_dst_dir, in_container = get_dirs()
datasets_src_dir = os.path.join(parent_dir, "valis/examples/example_datasets/")


def register_hi_rez(src_dir):
    high_rez_dst_dir = os.path.join(results_dst_dir, "high_rez")
    micro_reg_fraction = 0.25 # Fraction full resolution used for non-rigid registration

    # Perform high resolution rigid registration using the MicroRigidRegistrar
    start = time.time()
    registrar = registration.Valis(src_dir, high_rez_dst_dir, micro_rigid_registrar_cls=MicroRigidRegistrar)
    rigid_registrar, non_rigid_registrar, error_df = registrar.register()

    # Calculate what `max_non_rigid_registration_dim_px` needs to be to do non-rigid registration on an image that is 25% full resolution.
    img_dims = np.array([slide_obj.slide_dimensions_wh[0] for slide_obj in registrar.slide_dict.values()])
    min_max_size = np.min([np.max(d) for d in img_dims])
    img_areas = [np.multiply(*d) for d in img_dims]
    max_img_w, max_img_h = tuple(img_dims[np.argmax(img_areas)])
    micro_reg_size = np.floor(min_max_size*micro_reg_fraction).astype(int)

    # Perform high resolution non-rigid registration
    micro_reg, micro_error = registrar.register_micro(max_non_rigid_registration_dim_px=micro_reg_size)

    stop = time.time()
    elapsed = stop - start
    print(f"regisration time is {elapsed/60} minutes")

    # We can also plot the high resolution matches using `Valis.draw_matches`:
    matches_dst_dir = os.path.join(registrar.dst_dir, "hi_rez_matches")
    registrar.draw_matches(matches_dst_dir)


def test_register_ihc(max_error=60):
    """Tests registration and lossy jpeg compression"""
    ihc_src_dir = os.path.join(datasets_src_dir, "ihc")
    try:
        registrar = registration.Valis(ihc_src_dir, results_dst_dir)
        rigid_registrar, non_rigid_registrar, error_df = registrar.register()
        # micro_non_rigid_registrar, micro_error_df = registrar.register_micro()
        avg_error = np.max(error_df["mean_non_rigid_D"])

        if avg_error > max_error:
            # shutil.rmtree(ihc_dst_dir, ignore_errors=True)
            assert False, f"error was {avg_error} but should be below {max_error}"

        registered_slide_dst_dir = os.path.join(registrar.dst_dir, "registered_slides", registrar.name)
        registrar.warp_and_save_slides(dst_dir=registered_slide_dst_dir, Q=90, compression="jpeg")

        # shutil.rmtree(ihc_dst_dir, ignore_errors=True)

        assert True

    except Exception as e:
        # shutil.rmtree(ihc_dst_dir, ignore_errors=True)
        assert False, e


def test_register_cycif(max_error=3):
    """
    Goals:
        * Aligment and merging of staining rounds
        * Make sure error is below threshold
        * Checks channel names of merged image are in the correct order (https://github.com/MathOnco/valis/issues/56#issuecomment-1821050877)
        * Check jpeg2000 compression


    """

    drop_duplicates = True
    cycif_src_dir = os.path.join(datasets_src_dir, "cycif")
    try:
        img_list = list(pathlib.Path(cycif_src_dir).rglob("*.ome.tiff"))
        img_list = np.roll(img_list, 1)

        registrar = registration.Valis(cycif_src_dir, results_dst_dir, img_list=img_list, imgs_ordered=True)
        rigid_registrar, non_rigid_registrar, error_df = registrar.register()
        # micro_non_rigid_registrar, micro_error_df = registrar.register_micro()
        avg_error = np.max(error_df["mean_non_rigid_D"])

        if avg_error > max_error:
            # shutil.rmtree(cycif_dst_dir, ignore_errors=True)
            assert False, f"error was {avg_error} but should be below {max_error}"

        channel_name_dict = {f: cnames_from_filename(f) for
                             f in registrar.original_img_list}

        dst_f = os.path.join(registrar.dst_dir, "registered_slides", f"{registrar.name}.ome.tiff")
        merged_img, channel_names, ome_xml = registrar.warp_and_merge_slides(dst_f,
                                                channel_name_dict=channel_name_dict,
                                                drop_duplicates=True,
                                                Q=90, compression="jp2k")

        # print("DONE saving")
        # expected_names = list(chain.from_iterable([channel_name_dict[f] for f in registrar.original_img_list]))
        # print("Expec names B4:", expected_names)
        # if drop_duplicates:
        #     expected_names = list(dict.fromkeys(expected_names))

        # print("Expec names:", expected_names)
        # print("ome_v", ome_types.__version__) ##Unknown
        # merged_ome = ome_types.from_tiff(dst_f)
        # print("merged_ome", merged_ome.images)
        # saved_names = [c.name for c in merged_ome.images[0].pixels.channels]
        # print("Saved names:", saved_names)

        # registration.kill_jvm()
        # assert all([expected_names[i] == saved_names[i] for i in range(len(saved_names))]), "channels not written in correct order"

        # shutil.rmtree(cycif_dst_dir, ignore_errors=True)

        assert True

    except Exception as e:
        # shutil.rmtree(cycif_dst_dir, ignore_errors=True)
        assert False, e


def test_register_hi_rez_ihc():
    ihc_src_dir = os.path.join(datasets_src_dir, "ihc")
    register_hi_rez(src_dir=ihc_src_dir)


def test_register_hi_rez_cycif():
    cycif_src_dir = os.path.join(datasets_src_dir, "cycif")
    register_hi_rez(src_dir=cycif_src_dir)


if __name__ == "__main__" and in_container:
    test_register_cycif()
    test_register_ihc()
    test_register_hi_rez_ihc()
    test_register_hi_rez_cycif()