#!/usr/bin/env python

from __future__ import annotations
import os
import sys
import copy
import cv2
import time
import numpy as np
from enum import Enum
from argparse import ArgumentParser
from typing import Tuple, Optional, List, Dict
import importlib.util
from abc import ABC, abstractmethod

class Color(Enum):
    BLACK          = '\033[30m'
    RED            = '\033[31m'
    GREEN          = '\033[32m'
    YELLOW         = '\033[33m'
    BLUE           = '\033[34m'
    MAGENTA        = '\033[35m'
    CYAN           = '\033[36m'
    WHITE          = '\033[37m'
    COLOR_DEFAULT  = '\033[39m'
    BOLD           = '\033[1m'
    UNDERLINE      = '\033[4m'
    INVISIBLE      = '\033[08m'
    REVERSE        = '\033[07m'
    BG_BLACK       = '\033[40m'
    BG_RED         = '\033[41m'
    BG_GREEN       = '\033[42m'
    BG_YELLOW      = '\033[43m'
    BG_BLUE        = '\033[44m'
    BG_MAGENTA     = '\033[45m'
    BG_CYAN        = '\033[46m'
    BG_WHITE       = '\033[47m'
    BG_DEFAULT     = '\033[49m'
    RESET          = '\033[0m'

    def __str__(self):
        return self.value

    def __call__(self, s):
        return str(self) + str(s) + str(Color.RESET)

class AbstractModel(ABC):
    """AbstractModel
    Base class of the model.
    """
    _runtime: str = 'onnx'
    _model_path: str = ''
    _class_score_th: float = 0.35
    _input_shapes: List[List[int]] = []
    _input_names: List[str] = []
    _output_shapes: List[List[int]] = []
    _output_names: List[str] = []

    # onnx/tflite
    _interpreter = None
    _inference_model = None
    _providers = None
    _swap = (2, 0, 1)
    _h_index = 2
    _w_index = 3

    # tflite
    _input_details = None
    _output_details = None

    @abstractmethod
    def __init__(
        self,
        *,
        runtime: Optional[str] = 'onnx',
        model_path: Optional[str] = '',
        class_score_th: Optional[float] = 0.35,
        providers: Optional[List] = [
            (
                'TensorrtExecutionProvider', {
                    'trt_engine_cache_enable': True,
                    'trt_engine_cache_path': '.',
                    'trt_fp16_enable': True,
                }
            ),
            'CUDAExecutionProvider',
            'CPUExecutionProvider',
        ],
    ):
        self._runtime = runtime
        self._model_path = model_path
        self._class_score_th = class_score_th
        self._providers = providers

        # Model loading
        if self._runtime == 'onnx':
            import onnxruntime # type: ignore
            session_option = onnxruntime.SessionOptions()
            session_option.log_severity_level = 3
            self._interpreter = \
                onnxruntime.InferenceSession(
                    model_path,
                    sess_options=session_option,
                    providers=providers,
                )
            self._providers = self._interpreter.get_providers()

            self._input_shapes = [
                input.shape for input in self._interpreter.get_inputs()
            ]
            self._input_names = [
                input.name for input in self._interpreter.get_inputs()
            ]
            self._output_shapes = [
                output.shape for output in self._interpreter.get_outputs()
            ]
            self._output_names = [
                output.name for output in self._interpreter.get_outputs()
            ]
            self._model = self._interpreter.run
            self._swap = (2, 0, 1)
            self._h_index = 2
            self._w_index = 3

        elif self._runtime == 'tflite':
            import tensorflow as tf # type: ignore
            self._interpreter = tf.lite.Interpreter(model_path=model_path)
            self._input_details = self._interpreter.get_input_details()
            self._output_details = self._interpreter.get_output_details()
            self._input_shapes = [
                input.get('shape', None) for input in self._input_details
            ]
            self._input_names = [
                input.get('name', None) for input in self._input_details
            ]
            self._output_shapes = [
                output.get('shape', None) for output in self._output_details
            ]
            self._output_names = [
                output.get('name', None) for output in self._output_details
            ]
            self._model = self._interpreter.get_signature_runner()
            self._swap = (0, 1, 2)
            self._h_index = 1
            self._w_index = 2

    @abstractmethod
    def __call__(
        self,
        *,
        input_datas: List[np.ndarray],
    ) -> List[np.ndarray]:
        datas = {
            f'{input_name}': input_data \
                for input_name, input_data in zip(self._input_names, input_datas)
        }
        if self._runtime == 'onnx':
            outputs = [
                output for output in \
                    self._model(
                        output_names=self._output_names,
                        input_feed=datas,
                    )
            ]
            return outputs
        elif self._runtime == 'tflite':
            outputs = [
                output for output in \
                    self._model(
                        **datas
                    ).values()
            ]
            return outputs

    @abstractmethod
    def _preprocess(
        self,
        *,
        image: np.ndarray,
        swap: Optional[Tuple[int,int,int]] = (2, 0, 1),
    ) -> np.ndarray:
        pass

    @abstractmethod
    def _postprocess(
        self,
        *,
        image: np.ndarray,
        boxes: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        pass

class YOLOX(AbstractModel):
    def __init__(
        self,
        *,
        runtime: Optional[str] = 'onnx',
        model_path: Optional[str] = 'yolox_n_body_head_hand_post_0461_0.4428_1x3x256x320_float32.tflite',
        class_score_th: Optional[float] = 0.35,
        providers: Optional[List] = None,
    ):
        """YOLOX

        Parameters
        ----------
        runtime: Optional[str]
            Runtime for YOLOX. Default: onnx

        model_path: Optional[str]
            ONNX/TFLite file path for YOLOX

        class_score_th: Optional[float]
            Score threshold. Default: 0.35

        providers: Optional[List]
            Providers for ONNXRuntime.
        """
        super().__init__(
            runtime=runtime,
            model_path=model_path,
            class_score_th=class_score_th,
            providers=providers,
        )

    def __call__(
        self,
        image: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """YOLOX

        Parameters
        ----------
        image: np.ndarray
            Entire image

        Returns
        -------
        boxes: np.ndarray
            Predicted boxes: [N, x1, y1, x2, y2]

        scores: np.ndarray
            Predicted box scores: [N, score]
        """
        temp_image = copy.deepcopy(image)

        # PreProcess
        resized_image = \
            self._preprocess(
                temp_image,
            )

        # Inference
        inferece_image = np.asarray([resized_image], dtype=np.float32)
        outputs = super().__call__(input_datas=[inferece_image])
        boxes = outputs[0]

        # PostProcess
        result_boxes, result_scores = \
            self._postprocess(
                image=temp_image,
                boxes=boxes,
            )

        return result_boxes, result_scores

    def _preprocess(
        self,
        image: np.ndarray,
    ) -> np.ndarray:
        """_preprocess

        Parameters
        ----------
        image: np.ndarray
            Entire image

        swap: tuple
            HWC to CHW: (2,0,1)
            CHW to HWC: (1,2,0)
            HWC to HWC: (0,1,2)
            CHW to CHW: (0,1,2)

        Returns
        -------
        resized_image: np.ndarray
            Resized and normalized image.
        """
        # Resize + Transpose
        resized_image = cv2.resize(
            image,
            (
                int(self._input_shapes[0][self._w_index]),
                int(self._input_shapes[0][self._h_index]),
            )
        )
        resized_image = resized_image.transpose(self._swap)
        resized_image = \
            np.ascontiguousarray(
                resized_image,
                dtype=np.float32,
            )

        return resized_image

    def _postprocess(
        self,
        image: np.ndarray,
        boxes: np.ndarray,
    ):
        """_postprocess

        Parameters
        ----------
        image: np.ndarray
            Entire image.

        boxes: np.ndarray
            float32[N, 7]

        Returns
        -------
        result_boxes: np.ndarray
            Predicted boxes: [N, x1, y1, x2, y2]

        result_scores: np.ndarray
            Predicted box confs: [N, score]
        """
        image_height = image.shape[0]
        image_width = image.shape[1]

        """
        Detector is
            N -> Number of boxes detected
            batchno -> always 0: BatchNo.0

        batchno_classid_score_x1y1x2y2: float32[N,7]
        """
        image_height = image.shape[0]
        image_width = image.shape[1]

        result_boxes = []
        result_scores = []

        if len(boxes) > 0:
            scores = boxes[:, 2:3]
            keep_idxs = scores[:, 0] > self._class_score_th
            scores_keep = scores[keep_idxs, :]
            boxes_keep = boxes[keep_idxs, :]

            if len(boxes_keep) > 0:
                for box, score in zip(boxes_keep, scores_keep):
                    class_id = int(box[1])
                    x_min = int(max(0, box[3]) * image_width / self._input_shapes[0][self._w_index])
                    y_min = int(max(0, box[4]) * image_height / self._input_shapes[0][self._h_index])
                    x_max = int(min(box[5], self._input_shapes[0][self._w_index]) * image_width / self._input_shapes[0][self._w_index])
                    y_max = int(min(box[6], self._input_shapes[0][self._h_index]) * image_height / self._input_shapes[0][self._h_index])
                    result_boxes.append(
                        [x_min, y_min, x_max, y_max, class_id]
                    )
                    result_scores.append(
                        score
                    )

        return np.asarray(result_boxes), np.asarray(result_scores)


def is_parsable_to_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False

def is_package_installed(package_name: str):
    """Checks if the specified package is installed.

    Parameters
    ----------
    package_name: str
        Name of the package to be checked.

    Returns
    -------
    result: bool
        True if the package is installed, false otherwise.
    """
    return importlib.util.find_spec(package_name) is not None


def main():
    parser = ArgumentParser()
    parser.add_argument(
        '-m',
        '--model',
        type=str,
        default='yolox_n_body_head_hand_post_0461_0.4428_1x3x256x320.onnx',
        help='ONNX/TFLite file path for YOLOX.',
    )
    parser.add_argument(
        '-v',
        '--video',
        type=str,
        default="0",
        help='Video file path or camera index.',
    )
    parser.add_argument(
        '-ep',
        '--execution_provider',
        type=str,
        choices=['cpu', 'cuda', 'tensorrt'],
        default='cpu',
        help='Execution provider for ONNXRuntime.',
    )
    args = parser.parse_args()

    # runtime check
    model_file: str = args.model
    model_ext: str = os.path.splitext(model_file)[1][1:].lower()
    runtime: str = None
    if model_ext == 'onnx':
        if not is_package_installed('onnxruntime'):
            print(Color.RED('ERROR: onnxruntime is not installed. pip install onnxruntime or pip install onnxruntime-gpu'))
            sys.exit(0)
    elif model_ext == 'tflite':
        if not is_package_installed('tensorflow'):
            print(Color.RED('ERROR: tensorflow is not installed. pip install tensorflow'))
            sys.exit(0)
    runtime = model_ext
    video: str = args.video
    execution_provider: str = args.execution_provider
    providers: List[Tuple[str, Dict] | str] = None
    if execution_provider == 'cpu':
        providers = [
            'CPUExecutionProvider',
        ]
    elif execution_provider == 'cuda':
        providers = [
            'CUDAExecutionProvider',
            'CPUExecutionProvider',
        ]
    elif execution_provider == 'tensorrt':
        providers = [
            (
                'TensorrtExecutionProvider', {
                    'trt_engine_cache_enable': True,
                    'trt_engine_cache_path': '.',
                    'trt_fp16_enable': True,
                }
            ),
            'CUDAExecutionProvider',
            'CPUExecutionProvider',
        ]

    # Model initialization
    model = YOLOX(
        runtime=runtime,
        model_path=model_file,
        providers=providers,
    )

    cap = cv2.VideoCapture(
        int(video) if is_parsable_to_int(video) else video
    )
    cap_fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
    video_writer = cv2.VideoWriter(
        filename='output.mp4',
        fourcc=fourcc,
        fps=cap_fps,
        frameSize=(w, h),
    )

    while cap.isOpened():
        res, image = cap.read()
        if not res:
            break

        debug_image = copy.deepcopy(image)

        start_time = time.perf_counter()
        boxes, scores = model(debug_image)
        elapsed_time = time.perf_counter() - start_time
        cv2.putText(
            debug_image,
            f'{elapsed_time*1000:.2f} ms',
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            debug_image,
            f'{elapsed_time*1000:.2f} ms',
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

        for box, score in zip(boxes, scores):
            classid: int = box[4]
            color = (255,255,255)
            if classid == 0:
                color = (255,0,0)
            elif classid == 1:
                color = (0,0,255)
            elif classid == 2:
                color = (0,255,0)
            cv2.rectangle(
                debug_image,
                (box[0], box[1]),
                (box[2], box[3]),
                (255,255,255),
                2,
            )
            cv2.rectangle(
                debug_image,
                (box[0], box[1]),
                (box[2], box[3]),
                color,
                1,
            )
            cv2.putText(
                debug_image,
                f'{score[0]:.2f}',
                (
                    box[0] if box[0]+50 < debug_image.shape[1] else debug_image.shape[1]-50,
                    box[1]-10 if box[1]-25 > 0 else 20
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                debug_image,
                f'{score[0]:.2f}',
                (
                    box[0] if box[0]+50 < debug_image.shape[1] else debug_image.shape[1]-50,
                    box[1]-10 if box[1]-25 > 0 else 20
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                color,
                1,
                cv2.LINE_AA,
            )

        key = cv2.waitKey(1)
        if key == 27: # ESC
            break

        cv2.imshow("test", debug_image)
        video_writer.write(debug_image)

    if video_writer:
        video_writer.release()

    if cap:
        cap.release()

if __name__ == "__main__":
    main()
