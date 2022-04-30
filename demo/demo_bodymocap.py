# Copyright (c) Facebook, Inc. and its affiliates.
import os
import sys
import os.path as osp
import torch
from torchvision.transforms import Normalize
import numpy as np
import cv2
import argparse
import json
import pickle
from datetime import datetime
from demo.demo_options import DemoOptions
from bodymocap.body_mocap_api import BodyMocap
from bodymocap.body_bbox_detector import BodyPoseEstimator
import mocap_utils.demo_utils as demo_utils
import mocap_utils.general_utils as gnu
from mocap_utils.timer import Timer
import renderer.image_utils as imu
from renderer.viewer2D import ImShow

from psbody.mesh import Mesh, MeshViewers
import numpy as np
import _pickle as pkl
from utils.smpl_paths import SmplPaths
from lib.ch_smpl import Smpl
from utils.interpenetration_ind import remove_interpenetration_fast
from os.path import join, split
from glob import glob

from mocap_utils.coordconv import convert_smpl_to_bbox, convert_bbox_to_oriIm
from dress_SMPL import load_smpl_from_file, pose_garment, retarget, dress


def try_on(smpl_model_data, vert_inds, img_original_bgr, pred_output, garment_org_body_unposed, garment_unposed,
           garment_tex):
    smpl = Smpl(smpl_model_data)
    smpl.pose[:] = pred_output['pred_body_pose']
    smpl.betas[:] = np.random.randn(10) * 0.01
    smpl.trans[:] = 0

    garment_unposed.set_texture_image(garment_tex)

    new_garment = dress(smpl, garment_org_body_unposed, garment_unposed, vert_inds, garment_tex)

    pred_vertices = new_garment.v
    pred_camera = pred_output['pred_camera']
    camScale = pred_camera[0]  # *1.15
    camTrans = pred_camera[1:]
    bboxTopLeft = pred_output['bbox_top_left']
    boxScale_o2n = pred_output['bbox_scale_ratio']
    img_original = img_original_bgr
    # Convert mesh to original image space (X,Y are aligned to image)
    # 1. SMPL -> 2D bbox
    # 2. 2D bbox -> original 2D image
    pred_vertices_bbox = convert_smpl_to_bbox(pred_vertices, camScale, camTrans)
    pred_vertices_img = convert_bbox_to_oriIm(
        pred_vertices_bbox, boxScale_o2n, bboxTopLeft, img_original.shape[1], img_original.shape[0])

    return dict(
        vertices=pred_vertices_img,
        faces=new_garment.f,
        ft=new_garment.ft,
        vt=new_garment.vt,
        t=new_garment.texture_image[:, :, [2, 1, 0]],
    )


def run_body_mocap(args, body_bbox_detector, body_mocap, visualizer):
    #Setup input data to handle different types of inputs
    input_type, input_data = demo_utils.setup_input(args)

    cur_frame = args.start_frame
    video_frame = 0
    timer = Timer()

    path = 'Multi-Garment_dataset/'
    all_scans = glob(path + '*')
    garment_classes = ['Pants', 'ShortPants', 'ShirtNoCoat', 'TShirtNoCoat', 'LongCoat']
    gar_dict = {}
    for gar in garment_classes:
        gar_dict[gar] = glob(join(path, '*', gar + '.obj'))

    dp = SmplPaths()
    vt, ft = dp.get_vt_ft_hres()
    smpl_model_data = dp.get_hres_smpl_model_data()
    smpl = Smpl(smpl_model_data)

    ## This file contains correspondances between garment vertices and smpl body
    fts_file = 'assets/garment_fts.pkl'
    vert_indices, fts = pkl.load(open(fts_file, 'rb'), encoding='latin1')
    fts['naked'] = ft

    ## Choose any garmet type as source
    garment_type1 = 'LongCoat'  # 'TShirtNoCoat' # 'Pants'
    # index1 = 0 # np.random.randint(0, len(gar_dict[garment_type1]))   ## Randomly pick from the digital wardrobe
    path1 = 'Multi-Garment_dataset/125611520103063/'  # split(gar_dict[garment_type1][index1])[0]

    garment_org_body_unposed1 = load_smpl_from_file(join(path1, 'registration.pkl'))
    garment_org_body_unposed1.pose[:] = 0
    garment_org_body_unposed1.trans[:] = 0
    garment_org_body_unposed1 = Mesh(garment_org_body_unposed1.v, garment_org_body_unposed1.f)

    garment_unposed1 = Mesh(filename=join(path1, garment_type1 + '.obj'))
    garment_tex1 = join(path1, 'multi_tex.jpg')
    vert_inds1 = vert_indices[garment_type1]

    garment_type2 = 'Pants'
    # index2 = 0 # np.random.randint(0, len(gar_dict[garment_type2]))   ## Randomly pick from the digital wardrobe
    path2 = 'Multi-Garment_dataset/125611520103063/'  # split(gar_dict[garment_type2][index2])[0]

    garment_org_body_unposed2 = load_smpl_from_file(join(path2, 'registration.pkl'))
    garment_org_body_unposed2.pose[:] = 0
    garment_org_body_unposed2.trans[:] = 0
    garment_org_body_unposed2 = Mesh(garment_org_body_unposed2.v, garment_org_body_unposed2.f)

    garment_unposed2 = Mesh(filename=join(path2, garment_type2 + '.obj'))
    garment_tex2 = join(path2, 'multi_tex.jpg')
    vert_inds2 = vert_indices[garment_type2]

    while True:
        timer.tic()
        # load data
@@ -115,13 +207,24 @@ def run_body_mocap(args, body_bbox_detector, body_mocap, visualizer):

        # extract mesh for rendering (vertices in image space and faces) from pred_output_list
        pred_mesh_list = demo_utils.extract_mesh_from_output(pred_output_list)
        pred_output = pred_output_list[0]

        m1 = try_on(smpl_model_data, vert_inds1, img_original_bgr,
                    pred_output, garment_org_body_unposed1,
                    garment_unposed1, garment_tex1)
        m2 = try_on(smpl_model_data, vert_inds2, img_original_bgr,
                    pred_output, garment_org_body_unposed2,
                    garment_unposed2, garment_tex2)

        pred_mesh_list = [m1, m2]

        # visualization
        res_img = visualizer.visualize(
            img_original_bgr,
            pred_mesh_list = pred_mesh_list, 
            body_bbox_list = body_bbox_list)

            pred_mesh_list=pred_mesh_list,
            # body_bbox_list = body_bbox_list
        )

        # show result in the screen
        if not args.no_display:
            res_img = res_img.astype(np.uint8)
            ImShow(res_img)
        # save result image
        if args.out_dir is not None:
            demo_utils.save_res_img(args.out_dir, image_path, res_img)
        # save predictions to pkl
        if args.save_pred_pkl:
            demo_type = 'body'
            demo_utils.save_pred_to_pkl(
                args, demo_type, image_path, body_bbox_list, hand_bbox_list, pred_output_list)
        timer.toc(bPrint=True,title="Time")
        print(f"Processed : {image_path}")
    #save images as a video
    if not args.no_video_out and input_type in ['video', 'webcam']:
        demo_utils.gen_video_out(args.out_dir, args.seq_name)
    if input_type =='webcam' and input_data is not None:
        input_data.release()
    cv2.destroyAllWindows()
def main():
    args = DemoOptions().parse()
    device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
    assert torch.cuda.is_available(), "Current version only supports GPU"
    # Set bbox detector
    body_bbox_detector = BodyPoseEstimator()
    # Set mocap regressor
    use_smplx = args.use_smplx
    checkpoint_path = args.checkpoint_body_smplx if use_smplx else args.checkpoint_body_smpl
    print("use_smplx", use_smplx)
    body_mocap = BodyMocap(checkpoint_path, args.smpl_dir, device, use_smplx)
    # Set Visualizer
    if args.renderer_type in ['pytorch3d', 'opendr']:
        from renderer.screen_free_visualizer import Visualizer
    else:
        from renderer.visualizer import Visualizer
    visualizer = Visualizer(args.renderer_type)
  
    run_body_mocap(args, body_bbox_detector, body_mocap, visualizer)
if __name__ == '__main__':
    main()
