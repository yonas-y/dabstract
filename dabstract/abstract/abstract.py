import numbers
import copy
import numpy as np
from tqdm import tqdm
import inspect
import os

import warnings

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from queue import Queue

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from typing import (
    Union,
    Any,
    List,
    TypeVar,
    Callable,
    Dict,
    Iterable,
    Generator,
    Tuple,
)

tvDictSeqAbstract = TypeVar("DictSeqAbstract")
tvSeqAbstract = TypeVar("SeqAbstract")

from dabstract.utils import list_intersection, list_difference
from dabstract.dataprocessor import ProcessingChain


class Abstract:
    def __init__(self, data):
        self._data = data
        self._abstract = True if isinstance(data, Abstract) else False
        if self._abstract:
            assert self._data.len_defined, (
                "Can only use %s it data has __len__" % self.__class__.__name__
            )
        else:
            assert hasattr(self._data, "__len__"), (
                "Can only use %s it data has __len__" % self.__class__.__name__
            )

    def __iter__(self) -> Any:
        for k in range(len(self)):
            yield self[k]

    def __getitem__(self, index: int) -> Any:
        return self.get(index)

    def __setitem__(self, k, v):
        raise NotImplementedError(
            "%s does not support item assignment." % self.__class__.__name__
        )

    def __call__(self, *args, **kwargs) -> Any:
        return self.get(*args, **kwargs)

    @property
    def len_defined(self):
        return True


class UnpackAbstract(Abstract):
    """
    The class is an abstract wrapper around a dictionary or DictSeqAbstract to unpack this dictionary in a lazy manner.
    Unpacking refers to copying the content of the dictionary into a list.

    Unpacking is based on the parameter "keys". For example, consider a Dict or DictSeqAbstract with the
    following content::

        $   data = {'data': [10,5,8],
        $           'label': [1,1,2],
        $           'other': ['some','other','information']

    To index this such that it returns a tuple containing the indexed item of keys 'data' and 'label',
    one can do::

        $   data_up = UnpackAbstract(data,keys=['data','label'])
        $   print(data_up[0])
        [10, 1]

    To index through the data one could directly use default indexing, i.e. [idx] or use the .get() method.

    The UnpackAbstract contains the following methods::

        .get - return entry form UnpackAbstract

    The full explanation for each method is provided as a docstring at each method.

    Parameters
    ----------
    data : dict or tvDictSeqAbstract
        dictionary or DictSeqAbstract to be unpacked
    keys : List[str]
        list containing the strings that are used as keys

    Returns
    ----------
    UnpackAbstract class
    """

    def __init__(self, data: dict or tvDictSeqAbstract, keys: List[str]):
        super().__init__(data)
        self._keys = keys

    def get(self, index: int, return_info: bool = False) -> List[Any]:
        """
        Parameters
        ----------
        index : int
            index to retrieve data from
        return_info : bool
            return tuple (data, info) if True else data (default = False)
            info contains the information that has been propagated through the chain of operations
        Returns
        ----------
        List of Any
        """
        if isinstance(index, numbers.Integral):
            out = list()
            if len(self._keys) == 1:
                out = self._data[self._keys[0]][index]
            else:
                for key in self._keys:
                    out.append(self._data[key][index])
            if return_info:
                return out, dict()
            else:
                return out
        else:
            return self._data[index]

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return self._data.__repr__() + "\n Unpack of keys: " + str(self._keys)


def parallel_op(
    data: Iterable,
    type: str = "threadpool",
    workers: int = 0,
    buffer_len: int = 3,
    return_info: bool = False,
    *args: list,
    **kwargs: Dict
) -> Generator:
    """Apply a multiproc generator to the input sequence"""
    # check
    assert hasattr(data, "__len__"), "Can only use parallel_op it object has __len__"

    # define function to evaluate
    if isinstance(data, Abstract):

        def func(index):
            return data.get(index, *args, return_info=return_info, **kwargs)

    else:

        def func(index):
            return data[index]

    # get parallel util
    if type == "threadpool":
        parr = ThreadPoolExecutor
    elif type == "processpool":
        parr = ProcessPoolExecutor

    # create generator
    if workers > 0:
        Q = Queue()
        with parr(workers) as E:
            for k in range(len(data)):
                if Q.qsize() >= buffer_len:
                    yield Q.get().result()
                Q.put(E.submit(func, k))
            while not Q.empty():
                yield Q.get().result()
    else:
        for k in range(len(data)):
            yield func(k)


class DataAbstract(Abstract):
    """Allow for multi-indexing and multi-processing on a sequence or dictseq"""

    def __init__(
        self,
        data: Iterable,
        output_datatype: str = "auto",
        workers: int = 0,
        buffer_len: int = 3,
        load_memory: bool = False,
    ):
        super().__init__(data)
        self._output_datatype = output_datatype
        self._workers = workers
        self._buffer_len = buffer_len
        self._load_memory = load_memory

    def __iter__(self) -> Generator:
        return parallel_op(
            self._data,
            *self._args,
            workers=self._workers,
            buffer_len=self._buffer_len,
            return_info=False,
            **self._kwargs,
        )

    def get(
        self,
        index: Iterable,
        return_info: bool = False,
        workers: int = 0,
        buffer_len: int = 3,
        return_generator: bool = False,
        verbose: bool = False,
        *args: list,
        **kwargs: Dict
    ) -> Any:
        if isinstance(index, numbers.Integral):
            if self._abstract:
                data, info = self._data.get(
                    index, return_info=True, *args, **kwargs, **self._kwargs
                )
            else:
                data, info = self._data[index], {}
            return (data, info) if return_info else data
        elif isinstance(index, (tuple, list, np.ndarray, slice)):
            # generator
            _data = SelectAbstract(self._data, index)
            gen = parallel_op(
                _data,
                *args,
                workers=workers,
                buffer_len=buffer_len,
                return_info=return_info,
                **kwargs,
            )
            # return
            if return_generator:
                return gen
            else:
                for k, tmp in enumerate(tqdm(gen, disable=not verbose)):
                    if return_info:
                        tmp_data, tmp_info = tmp[0], tmp[1]
                    else:
                        tmp_data = tmp
                    if len(_data) == 1:
                        return (tmp_data, tmp_info) if return_info else tmp_data
                    else:
                        if k == 0:
                            if return_info:
                                info_out = [dict()] * len(self._data)
                            if isinstance(
                                tmp_data, (np.ndarray)
                            ) and self._output_datatype in ("numpy", "auto"):
                                data_out = np.zeros((len(_data),) + tmp_data.shape)
                            elif isinstance(
                                tmp_data, (np.int, np.int64, int, np.float64)
                            ) and self._output_datatype in ("numpy", "auto"):
                                data_out = np.zeros((len(_data), 1))
                            elif self._output_datatype in ("list", "auto"):
                                data_out = [None] * len(_data)
                        elif self._output_datatype == "auto" and isinstance(
                            data_out, np.ndarray
                        ):
                            if (
                                np.squeeze(data_out[0]).shape
                                != np.squeeze(tmp_data).shape
                            ):
                                tmp_data_out = data_out
                                data_out = [None] * len(data_out)
                                for k in range(len(tmp_data_out)):
                                    data_out[k] = tmp_data_out[k]
                        data_out[k] = tmp_data
                        if return_info:
                            info_out[k] = tmp_info
                return (data_out, info_out) if return_info else data_out
        elif isinstance(index, str):
            return DataAbstract(KeyAbstract(self, index))
        else:
            raise TypeError(
                "Index should be a number. Note that a str works too as it does not provide any error but it will only return a \n \
                            value which is not None in case it actually contains a key. \n \
                            This is because a SeqAbstract may contain a DictSeqAbstract with a single active key \n \
                            and other data including no keys."
            )

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return (
            class_str(self._data)
            + "\n data abstract: multi_processing "
            + str((True if self._workers > 0 else False))
        )


class MapAbstract(Abstract):
    """
    The class applies a mapping to data in a lazy manner.

    For example, consider the following function::

        $   def some_function(input, multiplier, logarithm=False)
        $       output = input * multiplier
        $       if logarithm:
        $           output = np.log10(output)
        $       return output

    You can apply this function with multiplier=5 and logarithm=True as follows::

        $   data = [1,2,3]
        $   data_map = MapAbstract(data,map_fct=some_function, 5, logarithm=True)
        $   print(data_map[0])
        0.6989

    Similarly, one could use a lambda function::

        $   data = [1,2,3]
        $   data_map = MapAbstract(data, lambda x: np.log10(x*5))
        $   print(data_map[0])
        0.6989

    Another example is to use the ProcessingChain. This would allow propagation of information.
    For example, assume the following ProcessingChain::

        $   class custom_processor(Processor):
        $       def process(self, data, **kwargs):
        $           return data + 1, {'multiplier': 3}
        $   class custom_processor2(Processor):
        $       def process(self, data, **kwargs):
        $           return data * kwargs['multiplier'], {}
        $   dp = ProcessingChain()
        $   dp.add(custom_processor)
        $   dp.add(custom_processor2)

    And add this to some data with a MapAbstract::

        $   data = [1,2,3]
        $   data_map = MapAbstract(data,map_fct=dp)
        $   print(data_map[0])
        6

    When using a ProcessingChain one can utilise the fact that it propagates the so-called 'info' through lazy operations.
    To obtain the information that has been progated, one can use the .get() method::

        $   print(data_map.get(0, return_info=True)
        (6, {'multiplier': 3, 'output_shape': ()})

    For more information on how to use a ProcessingChain, please check dabstract.dataprocessor.ProcessingChain.

    There are cases when one would like to use a function that has not been defined as a dabstract Processor, but
    where it still is desired to for example propagate information, e.g. sampling frequency.
    One can encapsulate information in a mapping function such as::

        $   data = [1,2,3]
        $   data_map = MapAbstract(data, (lambda x): x, info=({'fs': 16000}, {'fs': 16000}, {'fs': 16000}))
        $   print(data_map[0])
        (1, {'fs': 16000})

    To index through the data one could directly use default indexing, i.e. [idx] or use the .get() method.

    The MapAbstract contains the following methods::

        .get - return entry from MapAbstract
        .keys - return attribute keys of data

    The full explanation for each method is provided as a docstring at each method.

    Parameters
    ----------
    data : Iterable
        Iterable object to be mapped
    map_fct : Callable
        Callable object that defines the mapping
    info : List[Dict]
        List of Dictionary containing information that will be propagated through the chain of operations.
        Useful when the mapping function is not a ProcessingChain
        (default = None)
    arg : list
        additional param to provide to the function if needed
    kwargs : dict
        additional param to provide to the function if needed

    Returns
    ----------
    MapAbstract class
    """

    def __init__(
        self,
        data: Iterable,
        map_fct: Callable,
        info: List[Dict] = None,
        *args: list,
        **kwargs: Dict
    ):
        super().__init__(data)
        assert callable(map_fct), map_fct
        self._map_fct = map_fct
        self._chain = True if isinstance(map_fct, ProcessingChain) else False
        self._info = info
        self._args = args
        self._kwargs = kwargs

    def get(
        self, index: int, return_info: bool = False, *args: List, **kwargs: Dict
    ) -> Union[List, np.ndarray, Any]:
        """

        Parameters
        ----------
        index : int
            index to retrieve data from
        return_info : bool
            return tuple (data, info) if True else data (default = False)
            info contains the information that has been propagated through the chain of operations
        arg : List
            additional param to provide to the function if needed
        kwargs : Dict
            additional param to provide to the function if needed

        Returns
        -------
        List OR np.ndarray OR Any
        """
        if isinstance(index, numbers.Integral):
            if index < 0:
                index = index % len(self)
            if self._abstract:
                data, info = self._data.get(index, *args, return_info=True, **kwargs)
            else:
                data, info = self._data[index], kwargs
            if self._chain:
                data, info = self._map_fct(
                    data, *self._args, **dict(self._kwargs, **info), return_info=True
                )
            else:
                data = self._map_fct(data, *self._args, **dict(self._kwargs, **info))
            if self._info is not None:
                info = dict(info, **self._info[index])
            return (data, info) if return_info else data
        elif isinstance(index, str):
            warnings.warn(
                "Ignoring a mapping. Mapping works on __getitem__, so if you have a nested DictSeqAbstract with active key, then you will access the active key without mapping and the meta information"
            )
            return self._data[index]
        else:
            raise TypeError(
                "Index should be a number. Note that a str works too as it does not provide any error but it will only a \
                            value which is not None in case a it actually contains a key. \
                            This is because a SeqAbstract may contain a DictSeqAbstract with a single active key \
                            and other data including no keys."
            )
            # ToDo(gert) add a way to raise a error in case data does not contain any key.

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return class_str(self._data) + "\n map: " + str(self._map_fct)


def Map(
    data,
    map_fct: Callable,
    info: List[Dict] = None,
    lazy: bool = True,
    workers: int = 1,
    buffer_len: int = 3,
    *arg: list,
    **kwargs: Dict
) -> Union[MapAbstract, DataAbstract, np.ndarray, list]:
    """
    Factory function to allow for choice between lazy and direct mapping.

    For both an instance of MapAbstract is created. Different from lazy mapping, is that with direct mapping all examples
    are immediately evaluated.

    To have more information on mapping, please read the docstring of MapAbstract().

    Parameters
    -------
    data :
        The data that needs to be mapped
    map_fct : Callable
        Callable object that defines the mapping
    info : List[Dict]
        List of Dictionary containing information that has been propagated through the chain of operations
        (default = None)
    lazy : bool
        apply lazily or not (default = True)
    workers : int
        amount of workers used for loading the data (default = 1)
    buffer_len : int
        buffer_len of the pool (default = 3)
    arg : list
        additional param to provide to the function if needed
    kwargs : Dict
        additional param to provide to the function if needed

    Returns
    -------
    MapAbstract OR DataAbstract OR np.ndarray OR list
    """

    if lazy:
        return MapAbstract(data, map_fct, *arg, info=info, **kwargs)
    else:
        return DataAbstract(
            MapAbstract(data, map_fct, *arg, info=info, **kwargs),
            workers=workers,
            buffer_len=buffer_len,
        )[:]


# ToDo(gert)
# def Replicate(data, factor, type = 'on_sample', lazy=True, workers=1, buffer_len=3, *arg, **kwargs):
#     """Factory function to allow for choice between lazy and direct replication
#     """
#     _abstract = (True if isinstance(data, abstract) else False)
#     if lazy:
#         return ReplicateAbstract(data, factor, type = 'on_sample', **kwargs)
#     else:
#         #ToDo: replace by a list and np equivalent
#         return DataAbstract(ReplicateAbstract(data, factor, type = 'on_sample', *arg, **kwargs),
#                             workers=workers,
#                             buffer_len=buffer_len)[:]
# ToDo(gert)
# class ReplicateAbstract(abstract):
#     """Replicate data a particular factor
#     """
#     def __init__(self, data, factor, type = 'on_sample', **kwargs):
#         self._data = data
#         self._type = type
#         self._factor = factor
#         self._abstract = (True if isinstance(data, abstract) else False)
#         if self._type == 'on_sample':
#             self.rep_function = (lambda x: int(np.floor(x / self._factor)))
#         elif self._type == 'full':
#             self.rep_function = (lambda x: int(np.floor(x / len(self._data))))
#         else:
#             raise NotImplemented
##
#     def get(self, index, return_info=False, *arg, **kwargs):
#         if isinstance(index, numbers.Integral):
#             if index < 0:
#                 index = index % len(self)
#             assert index < len(self)
#             k = self.rep_function(index)
#             if self._abstract:
#                 data, info = self._data.get(k, return_info=True, *arg, **kwargs, **self._kwargs)
#             else:
#                 data, info = self._data[k], {}
#             return ((data, info) if return_info else data)
#         elif isinstance(index, str):
#             return KeyAbstract(self, index)
#         else:
#             raise TypeError('Index should be a str or number')
#
#     def __len__(self):
#         return len(self._data) * self._factor
#
#     def __repr__(self):
#         return self._data.__repr__() + "\n replicate: " + str(
#             self._factor) + ' ' + self._type


class SampleReplicateAbstract(Abstract):
    """
    Replicate data on sample-by-sample basis.

    Sample replication is based on the parameter 'factor'. This parameter is used to control to replication ratio.
    For example::

        $ data = [1, 2, 3]
        $ data_rep = SampleReplicateAbstract([1, 2, 3], factor = 3)
        $ print([tmp for tmp in data_rep])
        [1, 1, 1, 2, 2, 2, 3, 3, 3]

    The SampleReplicateAbstract contains the following methods::

    .get - return entry form SampleReplicateAbstract
    .keys - return the list of keys

    The full explanation for each method is provided as a docstring at each method.

    Parameters
    -------
    data : Iterable
        input data to replicate on a sample-by-sample basis
    factor : int
        integer used to compute an index for element in data used as sample
    kwargs : Dict
        additional param to provide to the function if needed

    Returns
    -------
    SampleReplicateAbstract class
    """

    def __init__(self, data: Iterable, factor: int, **kwargs: Dict):
        super().__init__(data)
        self._factor = factor
        if isinstance(self._factor, numbers.Integral):
            self._factor = self._factor * np.ones(len(data))

    def get(
        self, index: int, return_info: bool = False, *arg: List, **kwargs: Dict
    ) -> Union[List, np.ndarray, Any]:
        """
        Parameters
        ----------
        index : int
            index to sample from data
        return_info : bool
            return tuple (data, info) if True else data (default = False)
        arg : List
            additional param to provide to the function if needed
        kwargs : Dict
            additional param to provide to the function if needed

        Returns
        -------
        List OR np.ndarray OR Any
        """
        if isinstance(index, numbers.Integral):
            assert index < len(self), "Index should be lower than len(dataset)"
            if index < 0:
                index = index % len(self)
            for k, factor in enumerate(self._factor):
                if factor <= index:
                    index -= factor
                else:
                    # get
                    if self._abstract:
                        data, info = self._data.get(k, return_info=True, **kwargs)
                    else:
                        data, info = self._data[k], dict()
                    # return
                    return (data, info) if return_info else data
        elif isinstance(index, str):
            return KeyAbstract(self, index)
        else:
            raise TypeError("Index should be a str or number")

    def __len__(self) -> int:
        return int(np.sum(self._factor))

    def __repr__(self) -> str:
        return (
            self._data.__repr__()
            + "\n replicate: "
            + str(self._factor.min())
            + " - "
            + str(self._factor.max())
        )


def SampleReplicate(
    data: Iterable,
    factor: int,
    lazy: bool = True,
    workers: int = 1,
    buffer_len: int = 3,
    *arg: List,
    **kwargs: Dict
) -> Union[SampleReplicateAbstract, DataAbstract, np.ndarray, list]:
    """
    Factory function to allow for choice between lazy and direct sample replication.

    For both an instance of SampleReplicateAbstract is created. Different from sample replication, is that with direct
    sample replication all examples are immediately evaluated.

    To have more information on sample replication, please read the docstring of SampleReplicateAbstract().

    Parameters
    -------
    data : Iterable
        input data to perform sample replication on
    factor : int
        integer used to compute an index for element in data used as sample
    lazy : bool
        apply lazily or not (default = True)
    workers : int
        amount of workers used for loading the data (default = 1)
    buffer_len : int
        buffer_len of the pool (default = 3)
    arg : List
        additional param to provide to the function if needed
    kwargs : Dict
        additional param to provide to the function if needed

    Returns
    -------
    SampleReplicateAbstract OR DataAbstract OR np.ndarray OR list
    """
    if lazy:
        return SampleReplicateAbstract(data, factor, *arg, **kwargs)
    else:
        # ToDo: replace by a list and np equivalent
        return DataAbstract(
            SampleReplicateAbstract(data, factor, *arg, **kwargs),
            workers=workers,
            buffer_len=buffer_len,
        )[:]


class SplitAbstract(Abstract):
    """
    The class is an abstract wrapper around an iterable to split this iterable in a lazy manner. Splitting refers
    to dividing the a particular example in multiple chunks, i.e. 60s examples are divided into 1s segments.

    Splitting is based on the parameters split_size, constraint, sample_len, sample_period and type.

    If type is set to 'samples' one has to define 'sample_len' and 'split_size'. In that case 'sample_len' refers to
    the amount of samples in one example, and split_size the size of one segment. 'sample_len' can be set as an integer
    if all examples are of the same size OR a list of integers if these are different between examples.

    If type is set to 'seconds' one has to define 'sample_len', 'split_size' and 'sample_period'. In this case each of
    these variables are not samples but defined in terms of seconds. 'sample_period' additionally specifies the sample period
    of these samples in order to properly split.

    The SplitAbstract contains the following methods::

        .get - return entry from SplitAbstract
        .keys - return attribute keys of data

    The full explanation for each method is provided as a docstring at each method.

    Parameters
    ----------
    data : Iterable
        Iterable object to be splitted
    split_size : int
        split size in seconds/samples depending on 'metric'
    constraint : str
        option 'power2' creates sizes with a order of 2 (used for autoencoders)
    sample_len : int or List[int]
        sample length (default = None)
    sample_period : int
        sample period (default = None)
    type : str
        split_size type ('seconds','samples') (default = 'seconds')

    Returns
    -------
    SplitAbstract class
    """

    def __init__(
        self,
        data: Iterable,
        split_size: int = None,
        constraint: str = None,
        sample_len: Union[int, List[int]] = None,
        sample_period: int = None,
        type: str = "seconds",
    ):
        super().__init__(data)
        assert split_size is not None, "Please provide a split in " + type
        self._type = type
        self._split_size = split_size
        self._constraint = constraint
        self._sample_len = sample_len
        if isinstance(self._sample_len, numbers.Integral):
            self._sample_len = self._sample_len * np.ones(len(data))
        self._sample_period = sample_period
        self._init_split()

    def _init_split(self):
        # init window_size
        if self._type == "seconds":
            self._window_size = int(self._split_size / self._sample_period)
        elif self._type == "samples":
            self._window_size = int(self._split_size)
        if self._constraint == "power2":
            self._window_size = int(2 ** np.ceil(np.log2(self._window_size)))
        assert self._window_size > 0
        # prepare splits
        self._split_range, self._split_len = [None] * len(self._data), np.zeros(
            len(self._data), dtype=int
        )
        for j in range(len(self._data)):
            num_frames = max(
                1,
                int(
                    np.floor(
                        (
                            (self._sample_len[j] - (self._window_size - 1) - 1)
                            / self._window_size
                        )
                        + 1
                    )
                ),
            )
            self._split_range[j] = np.tile(
                np.array([0, self._window_size]), (num_frames, 1)
            ) + np.tile(
                np.transpose(np.array([np.arange(num_frames) * self._window_size])),
                (1, 2),
            )
            self._split_len[j] = num_frames

    def get(
        self, index: int, return_info: bool = False, *args: List, **kwargs: Dict
    ) -> Union[List, np.ndarray, Any]:
        """
        Parameters
        ----------
        index : int
            index to retrieve data from
        return_info : bool
            return tuple (data, info) if True else data (default = False)
            info contains the information that has been propagated through the chain of operations
        arg : List
            additional param to provide to the function if needed
        kwargs : Dict
            additional param to provide to the function if needed
        Returns
        -------
        List OR np.ndarray OR Any
        """
        if isinstance(index, numbers.Integral):
            assert index < len(self)
            if index < 0:
                index = index % len(self)
            for k, split_len in enumerate(self._split_len):
                if split_len <= index:
                    index -= split_len
                else:
                    read_range = self._split_range[k][int(index)]
                    # get data
                    if self._abstract:
                        data, info = self._data.get(
                            k,
                            *args,
                            return_info=True,
                            read_range=read_range,
                            **kwargs,
                        )
                        if len(data) != np.diff(read_range)[0]:
                            data = data[read_range[0] : read_range[1]]
                    else:
                        data, info = self._data[k][read_range[0] : read_range[1]], {}
                    return (data, info) if return_info else data
        elif isinstance(index, str):
            return KeyAbstract(self, index)
        else:
            raise TypeError("Index should be a str or number")

    def __len__(self) -> int:
        return int(np.sum(self._split_len))

    def __repr__(self):
        return (
            self._data.__repr__()
            + "\n split: "
            + str(self._window_size * self._sample_period)
            + " "
            + self._type
        )


def Split(
    data: Iterable,
    split_size: int = None,
    constraint: str = None,
    sample_len: int = None,
    sample_period: int = None,
    type: str = "seconds",
    lazy: bool = True,
    workers: bool = 1,
    buffer_len: int = 3,
    *args: List,
    **kwargs: Dict
) -> Union[SplitAbstract, DataAbstract, np.ndarray, list]:
    """
    Factory function to allow for choice between lazy and direct example splitting.

    For both an instance of SplitAbstract is created. Different from lazy splitting, is that with direct splitting
    all examples are immediately evaluated.

    To have more information on splitting, please read the docstring of SplitAbstract().

    Parameters
    ----------
    data : Iterable
        Iterable object to be splitted
    split_size : int
        split size in seconds/samples depending on 'metric'
    constraint : str
        option 'power2' creates sizes with a order of 2 (used for autoencoders)
    sample_len : int
        sample length (default = None)
    sample_period : int
        sample period (default = None)
    type : str
        split_size type ('seconds','samples') (default = 'seconds')
    lazy : bool
        apply lazily or not (default = True)
    workers : int
        amount of workers used for loading the data (default = 1)
    buffer_len : int
        buffer_len of the pool (default = 3)
    arg : List
        additional param to provide to the function if needed
    kwargs : Dict
        additional param to provide to the function if needed

    Returns
    -------
    SplitAbstract OR DataAbstract OR np.ndarray OR list
    """
    if lazy:
        return SplitAbstract(
            data,
            split_size=split_size,
            constraint=constraint,
            sample_len=sample_len,
            sample_period=sample_period,
            type=type,
        )
    else:
        # ToDo: replace by a list and np equivalent
        return DataAbstract(
            SplitAbstract(
                data,
                split_size=split_size,
                constraint=constraint,
                sample_len=sample_len,
                sample_period=sample_period,
                type=type,
            ),
            workers=workers,
            buffer_len=buffer_len,
        )[:]


class SelectAbstract(Abstract):
    """
    Select a subset of your input sequence.

    Selection is based on a so called 'selector' which may have the form of a Callable or a list/np.ndarray of integers.
    Important for these Callables is that they accept two arguments: (1) data to base selection on and (2) index of the
    variable to be evaluated.

    Regarding the selector one can use  set of build-in selectors in dabstract.dataset.select, lambda function, an own custom function
    or indices. For example:

    1) random subsampling with::

        $  SelectAbstract(data, dabstract.dataset.select.random_subsample('ratio': 0.5))

    2) select based on a key and a particular value::

        $  SelectAbstract(data, dabstract.dataset.select.subsample_by_str('ratio': 0.5))

    3) use the lambda function such as::

        $  SelectAbstract(data, (lambda x,k: x['data']['subdb'][k]))

    4) directly use indices::

        $  indices = np.array[0,1,2,3,4])
        $  SelectAbstract(data, indices)

    If no 'eval_data' is used, the evaluation is performed on data available in 'data'. If 'eval_data' is available
    the evaluation is performed on 'eval_data'

    The SelectAbstract contains the following methods::

        .get - return entry from SelectAbstract
        .keys - return the list of keys

    The full explanation for each method is provided as a docstring at each method.

    Parameters
    ----------
    data : Iterable
        input data to perform selection on, if eval_data is None
    selector : List[int] OR Callable OR numbers.Integral
        selection criterium
    eval_data : Any
        if eval_data not None, then selection will be performed on eval_data, else data (default = None)
    kwargs : Dict
        additional param to provide to the function if needed

    Returns
    -------
    SelectAbstract class
    """

    def __init__(
        self,
        data: Iterable,
        selector: Union[List[int], Callable, numbers.Integral],
        eval_data: Any = None,
        *args,
        **kwargs: Dict
    ):
        super().__init__(data)
        assert hasattr(self._data, "__len__"), (
            "Can only use %s it object has __len__" % self.__class__.__name__
        )
        self._eval_data = data if eval_data is None else eval_data
        self._selector = selector
        self.set_indices(selector, *args, **kwargs)

    def set_indices(self, selector, *args, **kwargs):
        if callable(selector):
            if len(inspect.getfullargspec(selector).args) == 1:
                self._indices = selector(self._eval_data, *args, **kwargs)
            elif len(inspect.getfullargspec(selector).args) == 2:
                self._indices = np.where(
                    [
                        selector(self._eval_data, k, *args, **kwargs)
                        for k in range(len(self._eval_data))
                    ]
                )[0]
            else:
                raise NotImplementedError(
                    "Selector not supported. Please consult the docstring for options."
                )
        elif isinstance(selector, slice):
            self._indices = np.arange(
                (0 if selector.start is None else selector.start),
                (len(self._eval_data) if selector.stop is None else selector.stop),
                (1 if selector.step is None else selector.step),
            )
        elif isinstance(selector, (tuple, list, np.ndarray)):
            self._indices = selector
        elif isinstance(selector, numbers.Integral):
            self._indices = [selector]

    def get_indices(self):
        return self._indices

    def get(
        self, index: int, return_info: bool = False, *args: List, **kwargs: Dict
    ) -> Union[List, np.ndarray, Any]:
        """
        Parameters
        ----------
        index : int
            index to retrieve data from
        return_info : bool
            return tuple (data, info) if True else data (default = False)
        arg : List
            additional param to provide to the function if needed
        kwargs : Dict
            additional param to provide to the function if needed

        Returns
        -------
        List OR np.ndarray OR Any
        """
        if isinstance(index, numbers.Integral):
            assert index < len(self)
            index = self._indices[index]
            if self._abstract:
                data, info = self._data.get(index, *args, return_info=True, **kwargs)
            else:
                data, info = self._data[index], {}
            return (data, info) if return_info else data
        elif isinstance(index, str):
            return SelectAbstract(self._data[index], self._indices)
            # return KeyAbstract(self, index)
        else:
            raise TypeError("Index should be a str or number")

    def __len__(self) -> int:
        return len(self._indices)

    def __repr__(self) -> str:
        return self._data.__repr__() + "\n select: " + str(type(self._selector))


def Select(
    data,
    selector: Union[List[int], Callable, numbers.Integral],
    eval_data: Any = None,
    lazy: bool = True,
    workers: int = 1,
    buffer_len: int = 3,
    *args: List,
    **kwargs: Dict
) -> Union[SelectAbstract, DataAbstract, np.ndarray, list]:
    """
    Factory function to allow for choice between lazy and direct example selection.

    For both an instance of SelectAbstract is created. Different from lazy selecting, is that with direct selecting
    all examples are immediately evaluated.

    For more information on the functionality of Select please check the docstring of SelectAbstract().

    Parameters
    ----------
    data : Iterable
        input data to perform selection on, if eval_data is None
    selector : List[int] OR Callable OR numbers.Integral
        selection criterium
    eval_data : Any
        if eval_data not None, then selection will be performed on eval_data, else data (default = None)
    lazy : bool
        apply lazily or not (default = True)
    workers : int
        amount of workers used for loading the data (default = 1)
    buffer_len : int
        buffer_len of the pool (default = 3)
    arg/kwargs:
        additional param to provide to the function if needed

    Returns
    -------
    SelectAbstract OR DataAbstract OR np.ndarray OR list
    """
    if lazy:
        return SelectAbstract(data, selector, *args, eval_data=eval_data, **kwargs)
    else:
        # ToDo: replace by a list and np equivalent
        return DataAbstract(
            SelectAbstract(data, selector, *args, eval_data=eval_data, **kwargs),
            workers=workers,
            buffer_len=buffer_len,
        )[:]


class FilterAbstract(Abstract):
    """
    Filter on the fly. Interesting when the variable to filter on takes long to compute.

    When the FilterAbstract wrapper is applied, the length of your data is undefined as filtering is based on a net yet
    excecuted function 'filter_fct'.

    The FilterAbstract class contain the following methods
    ::
    .get - return entry from FilterAbstract
    .keys - show the set of keys

    The full explanation for each method is provided as a docstring at each method.

    Parameters
    ----------
    data : Iterable
        Iterable object to be filtered
    filter_fct : Callable
        Callable function that needs to be applied
    return_none : bool
        If True, return None if filter_fct is False
        If False, raises IndexError
    kwargs:
        additional param to provide to the function if needed

    Returns
    -------
    FilterAbstract class
    """

    def __init__(
        self,
        data: Iterable,
        filter_fct: Callable,
        return_none: bool = False,
        *args,
        **kwargs
    ):
        super().__init__(data)
        assert callable(filter_fct), filter_fct
        self._filter_fct = filter_fct
        self._return_none = return_none
        self._args = args
        self._kwargs = kwargs

    def __iter__(self) -> Generator:
        for data in self._data:
            if self._filter_fct(data, *self._args, **self._kwargs):
                yield data

    def get(
        self, index: int, return_info: bool = False, *arg: List, **kwargs: Dict
    ) -> Union[List, np.ndarray, Any]:
        """
        Parameters
        ----------
        index : int
            index to retrieve data from
        return_info : bool
            return tuple (data, info) if True else data (default = False)
        arg : List
            additional param to provide to the function if needed
        kwargs : Dict
            additional param to provide to the function if needed

        Returns
        -------
        List OR np.ndarray OR Any
        """
        if isinstance(index, numbers.Integral):
            assert index < len(self._data)
            if self._abstract:
                data, info = self._data.get(
                    index, return_info=True, *self._args, **self._kwargs
                )
            else:
                data, info = self._data[index], {}

            if self._filter_fct(data):
                return (data, info) if return_info else data
            elif not self._return_none:
                raise IndexError("Not available.")
            return None, info

        elif isinstance(index, str):
            return KeyAbstract(self, index)
        else:
            raise TypeError("Index should be a str or number")

    @property
    def len_defined(self):
        return self._return_none

    def __len__(self) -> int:
        if self.len_defined:
            return len(self._data)
        else:
            raise NotImplementedError("Length undefined when return_none is False")

    def __repr__(self) -> str:
        return self._data.__repr__() + "\n filter: " + str(type(self._filter_fct))


def Filter(
    data: Iterable,
    filter_fct: Callable,
    return_none: bool = True,
    lazy: bool = True,
    workers: int = 1,
    buffer_len: int = 3,
    *arg: List,
    **kwargs: Dict
) -> Union[FilterAbstract, DataAbstract, np.ndarray, List]:
    """
    Factory function to allow for choice between lazy and direct example selection.

    For both an instance of FilterAbstract is created. Different from lazy filtering, is that with direct filtering
    all examples are immediately evaluated.

    For more information on the functionality of Filter please check the docstring of FilterAbstract().

    Parameters
    ----------
    data : Iterable
        Iterable object to be filtered
    filter_fct : Callable
        Callable function that needs to be applied.
    return_none : bool
        If True, return None if filter_fct is False
        If False, raises IndexError
    lazy : bool
        apply lazily or not (default = True)
    workers : int
        amount of workers used for loading the data (default = 1)
    buffer_len : int
        buffer_len of the pool (default = 3)
    arg : List
        additional param to provide to the function if needed
    kwargs : Dict
        additional param to provide to the function if needed

    Returns
    -------
    FilterAbstract OR DataAbstract OR np.ndarray OR list
    """
    if lazy:
        return FilterAbstract(data, filter_fct, *arg, return_none=return_none, **kwargs)
    else:
        # ToDo: replace by a list and np equivalent
        tmp = DataAbstract(
            FilterAbstract(data, filter_fct, *arg, return_none=True, **kwargs),
            output_datatype="list",
            workers=workers,
            buffer_len=buffer_len,
        )[:]
        if return_none:
            return tmp
        else:
            return DataAbstract(
                SelectAbstract(tmp, lambda x, k: x[k] is not None),
                workers=workers,
                buffer_len=buffer_len,
            )[:]


class KeyAbstract(Abstract):
    """Error handling wrapper for a concatenated sequence where one might have a dictseq and the other doesnt.
    This will allow for key/index indexing even if the particular index does not have a key.
    """

    def __init__(self, data: Iterable, key: str):
        super().__init__(data)
        self._key = key

    def get(
        self, index: int, return_info: bool = False, *arg: List, **kwargs: Dict
    ) -> Union[List, np.ndarray, Any]:
        if isinstance(index, numbers.Integral):
            assert index < len(self)
            try:
                data, info = self._data.get(
                    key=self._key,
                    index=index,
                    *arg,
                    return_info=True,
                    **kwargs,
                )
            except:
                data, info = None, {}
            return (data, info) if return_info else data
        else:
            return KeyAbstract(self, index)

        # ToDo(gert)
        # if isinstance(index, str):
        #     assert key is None
        #     return self._data[index]
        # elif isinstance(index,numbers.Integral):
        #     if key is None:
        #         data, info = dict(), dict()
        #         for k, key in enumerate(self._active_keys):
        #             data[key], info[key] = self._data[key].get(index=index, return_info=True,**kwargs)
        #         if len(self._active_keys)==1:
        #             data, info = data[key], info[key]
        #     else:
        #         assert isinstance(key,str)
        #         data, info = self._data[key].get(index=index, return_info=True, **kwargs)
        #     return ((data, info) if return_info else data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return "key_abstract of key " + self._key + " on " + str(self._data)


class DictSeqAbstract(Abstract):
    """DictSeq base class"""

    def __init__(self, name: str = ""):
        self._nr_keys = 0
        self._name = name
        self._data = dict()
        self._active_keys = []
        self._lazy = dict()
        self._abstract = dict()
        self._adjust_mode = False

    def add(
        self,
        key: str,
        data: Iterable,
        lazy: bool = True,
        info: List[Dict] = None,
        **kwargs: Dict
    ) -> None:
        assert hasattr(
            data, "__getitem__"
        ), "provided data instance must have __getitem__ method."
        assert (
            key != "all"
        ), "The name 'all' is reserved for referring to all keys when applying a transform."
        assert hasattr(data, "__len__"), (
            "Can only use %s it object has __len__" % self.__class__.__name__
        )
        if not self._adjust_mode:
            if self._nr_keys > 0:
                assert len(data) == len(self), "len(self) is not the same as len(data)"
        new_key = False if key in self.keys() else True
        if (not lazy) and isinstance(data, Abstract):
            data = DataAbstract(data)[:]
        elif info is not None:
            data = SeqAbstract().concat(data, info=info)
        self._data.update({key: data})
        self._lazy.update({key: lazy})
        self._abstract.update({key: isinstance(data, Abstract)})
        if new_key:
            self._reset_active_keys()
            self._nr_keys += 1
        return self

    def add_dict(self, dct: Dict, lazy: bool = True) -> None:
        for key in dct:
            self.add(key, dct[key], lazy=lazy)
        return self

    def concat(
        self, data: Iterable, intersect: bool = False, adjust_base: bool = True
    ) -> None:
        from dabstract.dataset.helpers import FolderDictSeqAbstract

        if isinstance(data, list):
            for d in data:
                self.concat(d, intersect=intersect)
        else:
            self2 = self if adjust_base else copy.deepcopy(self)
            self2._adjust_mode = True
            data = copy.deepcopy(data)
            assert isinstance(data, DictSeqAbstract)
            if self2._nr_keys != 0:
                if not intersect:
                    assert (
                        data.keys() == self2.keys()
                    ), "keys do not match. Set intersect=True for keeping common keys."
                    keys = data.keys()
                else:
                    # get diff
                    keys = list_intersection(data.keys(), self2.keys())
                    rem_keys = list_difference(data.keys(), self2.keys())
                    # remove ones which are not identical
                    for rem_key in rem_keys:
                        self2.remove(rem_key)
                for key in keys:
                    if self2._lazy[key]:
                        # make sure that data format is as desired by the base dict
                        if not isinstance(
                            self2[key],
                            (SeqAbstract, DictSeqAbstract, FolderDictSeqAbstract),
                        ):
                            self2[key] = SeqAbstract().concat(self2[key])
                        # concatenate SeqAbstract
                        if isinstance(
                            data[key], SeqAbstract
                        ):  # if already a SeqAbstract, concat cleaner to avoid overhead
                            for _data in data[key]._data:
                                self2[key].concat(_data)
                        else:  # if not just concat at once
                            self2[key].concat(data[key])
                    else:
                        assert (
                            self2[key].__class__ == data[key].__class__
                        ), "When using lazy=False, datatypes should be same in case of concatenation."
                        if isinstance(self2[key], list):
                            self2[key] = self2[key] + data[key]
                        elif isinstance(self2[key], np.ndarray):
                            self2[key] = np.concatenate((self2[key], data[key]))
                self2._adjust_mode = False
            else:
                self2.__dict__.update(data.__dict__)

            return self2

    def remove(self, key: str) -> None:
        del self._data[key]
        self.reset_active_keys()
        self._nr_keys -= 1
        return self

    def add_map(self, key: str, map_fct: Callable, *arg: List, **kwargs: Dict) -> None:
        self[key] = Map(self[key], map_fct, lazy=self._lazy[key], *arg, **kwargs)

    def add_select(self, selector, *arg, eval_data=None, **kwargs):
        def iterative_select(data, indices, *arg, lazy=True, **kwargs):
            if isinstance(data, DictSeqAbstract):
                data._adjust_mode = True
                for key in data.keys():
                    if isinstance(data[key], DictSeqAbstract):
                        data[key] = iterative_select(
                            data[key], indices, *arg, lazy=data._lazy[key], **kwargs
                        )
                    else:
                        data[key] = Select(
                            data[key], indices, *arg, lazy=data._lazy[key], **kwargs
                        )
                data._adjust_mode = False
            else:
                data = Select(data, indices, *arg, lazy=lazy, **kwargs)
            return data

        # get indices for all to ensure no discrepancy between items
        indices = Select(
            self,
            selector,
            *arg,
            eval_data=(self if eval_data is None else eval_data),
            **kwargs,
        ).get_indices()
        # Add selection
        iterative_select(self, indices, *arg, **kwargs)

    def add_alias(self, key: str, new_key: str) -> None:
        assert new_key not in self.keys(), "alias key already in existing keys."
        self.add(new_key, self[key])

    def set_active_keys(self, keys: Union[List[str], str]) -> None:
        self._set_active_keys(keys)

    def reset_active_key(self) -> None:
        warnings.warn(
            "reset_active_key() in DictSeqAbstract is deprecated. Please use reset_active_keys()"
        )
        self._reset_active_keys()

    def reset_active_keys(self) -> None:
        self._reset_active_keys()

    def _set_active_keys(self, keys: Union[List[str], str]) -> None:
        if isinstance(keys, list):
            for key in keys:
                assert key in self.keys(), "key " + key + " does not exists."
            self._active_keys = keys
        else:
            assert keys in self.keys(), "key " + keys + " does not exists."
            self._active_keys = [keys]

    def _reset_active_keys(self) -> None:
        self._active_keys = self.keys()

    def get_active_keys(self) -> List[str]:
        return self._active_keys

    def __len__(self) -> int:
        nr_examples = [len(self._data[key]) for key in self._data]
        assert all([nr_example == nr_examples[0] for nr_example in nr_examples])
        return nr_examples[0] if len(nr_examples) > 0 else 0

    def __add__(self, other: Iterable) -> None:
        assert isinstance(other, DictSeqAbstract)
        return self.concat(other, adjust_base=False)

    def __setitem__(self, k: str, v: Any) -> None:
        assert isinstance(k, str), "Assignment only possible by key (str)."
        new_key = False if k in self.keys() else True
        lazy = True if new_key else self._lazy[k]  # make sure that lazy is kept
        self.add(k, v, lazy=lazy)

    def get(
        self,
        index: int,
        key: str = None,
        return_info: bool = False,
        *arg: List,
        **kwargs: Dict
    ) -> Union[List, np.ndarray, Any]:
        if isinstance(index, str):
            assert key is None
            return self._data[index]
        elif isinstance(index, numbers.Integral):
            if key is None:
                data, info = dict(), dict()
                for k, key in enumerate(self._active_keys):
                    if self._abstract[key]:
                        data[key], info[key] = self._data[key].get(
                            index=index, return_info=True, **kwargs
                        )
                    else:
                        data[key], info[key] = self._data[key][index], dict()
                if len(self._active_keys) == 1:
                    data, info = data[key], info[key]
            else:
                assert isinstance(key, str)
                data, info = self._data[key].get(
                    index=index, return_info=True, **kwargs
                )
            return (data, info) if return_info else data
        else:
            raise IndexError("index should be a number or str")

    def unpack(self, keys: List[str]) -> UnpackAbstract:
        return UnpackAbstract(self._data, keys)

    def keys(self) -> List[str]:
        return list(self._data.keys())

    def summary(self) -> Dict:
        summary = dict()
        for name, data in zip(self.keys(), self._data):
            summary[name] = data.summary()
        return summary

    def __repr__(self) -> str:
        return "dict_seq containing: " + str(self.keys())


class SeqAbstract(Abstract):
    """Seq base class"""

    def __init__(self, data: Iterable = None, name: str = "seq"):
        self._nr_sources = 0
        self._data = []
        self._info = []
        self._kwargs = []
        self._name = name
        if data is not None:
            if isinstance(data, list):
                for _data in data:
                    self.concat(_data)
            else:
                raise AssertionError("Input data should be a list")

    def concat(self, data: Iterable, info: List[Dict] = None, **kwargs: Dict) -> None:
        # Check
        assert hasattr(
            data, "__getitem__"
        ), "provided data instance must have __getitem__ method."
        if isinstance(data, DictSeqAbstract):
            assert (
                len(data._active_keys) == 1
            ), "You can only add a dict_abstract in case there is only one active key."
        assert hasattr(self._data, "__len__"), (
            "Can only use %s it object has __len__" % self.__class__.__name__
        )
        # Add
        data = copy.deepcopy(data)
        if isinstance(data, SeqAbstract):
            for _data in data._data:
                self.concat(_data)
        else:
            self._data.append(data)
        self._nr_sources += 1
        # Information to propagate to transforms or use for split
        if info is not None:
            assert isinstance(info, list), "info should be a list"
            assert isinstance(
                info[0], dict
            ), "The items in info should contain a dict()"
            assert len(info) == len(
                data
            ), "info should be a list with len(info)==len(data)"
        self._info.append(info)
        self._kwargs.append(kwargs)
        return self

    def __len__(self) -> int:
        return np.sum([len(data) for data in self._data])

    def __setitem__(self, index: int, value: Iterable):
        if isinstance(index, numbers.Integral):
            if index < 0:
                index = index % len(self)
            for k, data in enumerate(self._data):
                if len(data) <= index:
                    index -= len(data)
                else:
                    data[index] = value
                return None
            raise IndexError("Index should be lower than len(dataset)")
        elif isinstance(index, str):
            return KeyAbstract(self, index)
        else:
            raise IndexError(
                "index should be a number (or key in case of a nested dict_seq)."
            )

    def __add__(self, other: Union[tvSeqAbstract, Iterable]):
        # assert isinstance(other)
        return self.concat(other)

    def get(
        self,
        index: int,
        key: str = None,
        return_info: bool = False,
        *arg: List,
        **kwargs: Dict
    ) -> Union[List, np.ndarray, Any]:
        if isinstance(index, numbers.Integral):
            if index < 0:
                index = index % len(self)
            for k, data in enumerate(self._data):
                if len(data) <= index:
                    index -= len(data)
                else:
                    info = dict() if self._info[k] is None else self._info[k][index]
                    # get
                    if isinstance(self._data[k], Abstract):
                        data, info = data.get(
                            index,
                            *arg,
                            return_info=True,
                            **(info if key is None else dict(info, key=key)),
                            **kwargs,
                        )
                    else:
                        assert key is None
                        data, info = data[index], dict(**info, **kwargs)
                    # return
                    return (data, info) if return_info else data
            raise IndexError("Index should be lower than len(dataset)")
        elif isinstance(index, str):
            return KeyAbstract(self, index)
        else:
            raise IndexError(
                "index should be a number (or key in case of a nested dict_seq)."
            )

    def summary(self) -> Dict:
        return {"nr_examples": self.nr_examples, "name": self._name}

    def __repr__(self):
        r = "seq containing:"
        for data in self._data:
            if not isinstance(data, (Abstract)):
                r += "\n[ \t" + str(type(data)) + "\t]"
            else:
                r += "\n[ \t" + repr(data) + "\t]"
            # r += '\n'
        return r


def class_str(data: Callable):
    if isinstance(data, Abstract):
        return repr(data)
    else:
        return str(data.__class__)
    return
