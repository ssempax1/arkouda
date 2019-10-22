import json, struct
import numpy as np

from arkouda.client import generic_msg

__all__ = ["pdarray", "info"]

# supported dtypes
structDtypeCodes = {'int64': 'q',
                    'float64': 'd',
                    'bool': '?'}
DTypes = frozenset(structDtypeCodes.keys())
NUMBER_FORMAT_STRINGS = {'bool': '{}',
                         'int64': '{:n}',
                         'float64': '{:.17f}'}
bool = np.bool
int64 = np.int64
float64 = np.float64

def check_np_dtype(dt):
    """
    Assert that numpy dtype dt is one of the dtypes supported by arkouda, 
    otherwise raise TypeError.
    """
    if dt.name not in DTypes:
        raise TypeError("Unsupported type: {}".format(dt))

def translate_np_dtype(dt):
    """
    Split numpy dtype dt into its kind and byte size, raising TypeError 
    for unsupported dtypes.
    """
    # Assert that dt is one of the arkouda supported dtypes
    check_np_dtype(dt)
    trans = {'i': 'int', 'f': 'float', 'b': 'bool'}
    kind = trans[dt.kind]
    return kind, dt.itemsize

def resolve_scalar_dtype(val):
    """
    Try to infer what dtype arkouda_server should treat val as.
    """
    # Python bool or np.bool
    if isinstance(val, bool) or (hasattr(val, 'dtype') and val.dtype.kind == 'b'):
        return 'bool'
    # Python int or np.int* or np.uint*
    elif isinstance(val, int) or (hasattr(val, 'dtype') and val.dtype.kind in 'ui'):
        return 'int64'
    # Python float or np.float*
    elif isinstance(val, float) or (hasattr(val, 'dtype') and val.dtype.kind == 'f'):
        return 'float64'
    # Other numpy dtype
    elif hasattr(val, 'dtype'):
        return dtype.name
    # Other python type
    else:
        return str(type(val))

def parse_single_value(msg):
    """
    Attempt to convert a scalar return value from the arkouda server to a numpy
    scalar in Python. The user should not call this function directly.
    """
    dtname, value = msg.split()
    dtype = np.dtype(dtname)
    if dtype == np.bool:
        if value == "True":
            return np.bool(True)
        elif value == "False":
            return np.bool(False)
        else:
            raise ValueError("unsupported value from server {} {}".format(dtype.name, value))
    try:
        return dtype.type(value)
    except:
        raise ValueError("unsupported value from server {} {}".format(dtype.name, value))
    
BinOps = frozenset(["+", "-", "*", "/", "//", "%", "<", ">", "<=", ">=", "!=", "==", "&", "|", "^", "<<", ">>","**"])
OpEqOps = frozenset(["+=", "-=", "*=", "/=", "//=", "&=", "|=", "^=", "<<=", ">>=","**="])

# class for the pdarray
class pdarray:
    """
    The basic arkouda array class. This class contains only the 
    attributies of the array; the data resides on the arkouda 
    server. When a server operation results in a new array, arkouda 
    will create a pdarray instance that points to the array data on 
    the server. As such, the user should not initialize pdarray 
    instances directly.

    Attributes
    ----------
    name : str
        The server-side identifier for the array
    dtype : np.dtype
        The element type of the array
    size : int
        The number of elements in the array
    ndim : int
        The rank of the array (currently only rank 1 arrays supported)
    shape : tuple
        The sizes of each dimension of the array
    itemsize : int
        The size in bytes of each element
    """
    def __init__(self, name, dtype, size, ndim, shape, itemsize):
        self.name = name
        self.dtype = np.dtype(dtype)
        self.size = size
        self.ndim = ndim
        self.shape = shape
        self.itemsize = itemsize

    def __del__(self):
        global connected
        if connected:
            generic_msg("delete {}".format(self.name))

    def __len__(self):
        return self.shape[0]

    def __str__(self):
        global pdarrayIterThresh
        return generic_msg("str {} {}".format(self.name,pdarrayIterThresh) )

    def __repr__(self):
        global pdarrayIterTresh
        return generic_msg("repr {} {}".format(self.name,pdarrayIterThresh))
 
    def format_other(self, other):
        """
        Attempt to cast scalar other to the element dtype of this pdarray, 
        and print the resulting value to a string (e.g. for sending to a
        server command). The user should not call this function directly.
        """
        try:
            other = self.dtype.type(other)
        except:
            raise TypeError("Unable to convert {} to {}".format(other, self.dtype.name))
        if self.dtype == np.bool:
            return str(other)
        fmt = NUMBER_FORMAT_STRINGS[self.dtype.name]
        return fmt.format(other)
        
    # binary operators
    def binop(self, other, op):
        if op not in BinOps:
            raise ValueError("bad operator {}".format(op))
        # pdarray binop pdarray
        if isinstance(other, pdarray):
            if self.size != other.size:
                raise ValueError("size mismatch {} {}".format(self.size,other.size))
            msg = "binopvv {} {} {}".format(op, self.name, other.name)
            repMsg = generic_msg(msg)
            return create_pdarray(repMsg)
        # pdarray binop array-like is not implemented
        if hasattr(other, '__len__'): 
            return NotImplemented
        # pdarray binop scalar
        dt = resolve_scalar_dtype(other)
        if dt not in DTypes:
            raise TypeError("Unhandled scalar type: {} ({})".format(other, dt))
        msg = "binopvs {} {} {} {}".format(op, self.name, dt, NUMBER_FORMAT_STRINGS[dt].format(other))
        repMsg = generic_msg(msg)
        return create_pdarray(repMsg)

    # reverse binary operators
    # pdarray binop pdarray: taken care of by binop function
    def r_binop(self, other, op):
        if op not in BinOps:
            raise ValueError("bad operator {}".format(op))
        # pdarray binop array-like is not implemented
        if hasattr(other, '__len__'): 
            return NotImplemented
        # pdarray binop scalar
        dt = resolve_scalar_dtype(other)
        if dt not in DTypes:
            raise TypeError("Unhandled scalar type: {} ({})".format(other, dt))
        msg = "binopsv {} {} {} {}".format(op, dt, NUMBER_FORMAT_STRINGS[dt].format(other), self.name)
        repMsg = generic_msg(msg)
        return create_pdarray(repMsg)

    # overload + for pdarray, other can be {pdarray, int, float}
    def __add__(self, other):
        return self.binop(other, "+")

    def __radd__(self, other):
        return self.r_binop(other, "+")

    # overload - for pdarray, other can be {pdarray, int, float}
    def __sub__(self, other):
        return self.binop(other, "-")

    def __rsub__(self, other):
        return self.r_binop(other, "-")

    # overload * for pdarray, other can be {pdarray, int, float}
    def __mul__(self, other):
        return self.binop(other, "*")

    def __rmul__(self, other):
        return self.r_binop(other, "*")

    # overload / for pdarray, other can be {pdarray, int, float}
    def __truediv__(self, other):
        return self.binop(other, "/")

    def __rtruediv__(self, other):
        return self.r_binop(other, "/")

    # overload // for pdarray, other can be {pdarray, int, float}
    def __floordiv__(self, other):
        return self.binop(other, "//")

    def __rfloordiv__(self, other):
        return self.r_binop(other, "//")

    def __mod__(self, other):
        return self.binop(other, "%")

    def __rmod__(self, other):
        return self.r_binop(other, "%")

    # overload << for pdarray, other can be {pdarray, int}
    def __lshift__(self, other):
        return self.binop(other, "<<")

    def __rlshift__(self, other):
        return self.r_binop(other, "<<")

    # overload >> for pdarray, other can be {pdarray, int}
    def __rshift__(self, other):
        return self.binop(other, ">>")

    def __rrshift__(self, other):
        return self.r_binop(other, ">>")

    # overload & for pdarray, other can be {pdarray, int}
    def __and__(self, other):
        return self.binop(other, "&")

    def __rand__(self, other):
        return self.r_binop(other, "&")

    # overload | for pdarray, other can be {pdarray, int}
    def __or__(self, other):
        return self.binop(other, "|")

    def __ror__(self, other):
        return self.r_binop(other, "|")

    # overload | for pdarray, other can be {pdarray, int}
    def __xor__(self, other):
        return self.binop(other, "^")

    def __rxor__(self, other):
        return self.r_binop(other, "^")

    def __pow__(self,other): 
        return self.binop(other,"**")
    
    def __rpow__(self,other): 
        return self.r_binop(other,"**")

    # overloaded comparison operators
    def __lt__(self, other):
        return self.binop(other, "<")

    def __gt__(self, other):
        return self.binop(other, ">")

    def __le__(self, other):
        return self.binop(other, "<=")

    def __ge__(self, other):
        return self.binop(other, ">=")

    def __eq__(self, other):
        return self.binop(other, "==")

    def __ne__(self, other):
        return self.binop(other, "!=")

    # overload unary- for pdarray implemented as pdarray*(-1)
    def __neg__(self):
        return self.binop(-1, "*")

    # overload unary~ for pdarray implemented as pdarray^(~0)
    def __invert__(self):
        if self.dtype == np.int64:
            return self.binop(~0, "^")
        if self.dtype == np.bool:
            return self.binop(True, "^")
        return NotImplemented

    # op= operators
    def opeq(self, other, op):
        if op not in OpEqOps:
            raise ValueError("bad operator {}".format(op))
        # pdarray op= pdarray
        if isinstance(other, pdarray):
            if self.size != other.size:
                raise ValueError("size mismatch {} {}".format(self.size,other.size))
            generic_msg("opeqvv {} {} {}".format(op, self.name, other.name))
            return self
        # pdarray op= array-like is not implemented
        if hasattr(other, '__len__'): 
            return NotImplemented
        # pdarray binop scalar
        # opeq requires scalar to be cast as pdarray dtype
        try:
            other = self.dtype.type(other)
        except: # Can't cast other as dtype of pdarray
            return NotImplemented
        msg = "opeqvs {} {} {} {}".format(op, self.name, self.dtype.name, self.format_other(other))
        generic_msg(msg)
        return self

    # overload += pdarray, other can be {pdarray, int, float}
    def __iadd__(self, other):
        return self.opeq(other, "+=")

    # overload -= pdarray, other can be {pdarray, int, float}
    def __isub__(self, other):
        return self.opeq(other, "-=")

    # overload *= pdarray, other can be {pdarray, int, float}
    def __imul__(self, other):
        return self.opeq(other, "*=")

    # overload /= pdarray, other can be {pdarray, int, float}
    def __itruediv__(self, other):
        return self.opeq(other, "/=")

    # overload //= pdarray, other can be {pdarray, int, float}
    def __ifloordiv__(self, other):
        return self.opeq(other, "//=")

    # overload <<= pdarray, other can be {pdarray, int, float}
    def __ilshift__(self, other):
        return self.opeq(other, "<<=")

    # overload >>= pdarray, other can be {pdarray, int, float}
    def __irshift__(self, other):
        return self.opeq(other, ">>=")

    # overload &= pdarray, other can be {pdarray, int, float}
    def __iand__(self, other):
        return self.opeq(other, "&=")

    # overload |= pdarray, other can be {pdarray, int, float}
    def __ior__(self, other):
        return self.opeq(other, "|=")

    # overload ^= pdarray, other can be {pdarray, int, float}
    def __ixor__(self, other):
        return self.opeq(other, "^=")
    def __ipow__(self, other):
        return self.opeq(other,"**=")

    # overload a[] to treat like list
    def __getitem__(self, key):
        if np.isscalar(key) and resolve_scalar_dtype(key) == 'int64':
            if (key >= 0 and key < self.size):
                repMsg = generic_msg("[int] {} {}".format(self.name, key))
                fields = repMsg.split()
                # value = fields[2]
                return parse_single_value(' '.join(fields[1:]))
            else:
                raise IndexError("[int] {} is out of bounds with size {}".format(key,self.size))
        if isinstance(key, slice):
            (start,stop,stride) = key.indices(self.size)
            if v: print(start,stop,stride)
            repMsg = generic_msg("[slice] {} {} {} {}".format(self.name, start, stop, stride))
            return create_pdarray(repMsg);
        if isinstance(key, pdarray):
            kind, itemsize = translate_np_dtype(key.dtype)
            if kind not in ("bool", "int"):
                raise TypeError("unsupported pdarray index type {}".format(key.dtype))
            if kind == "bool" and self.size != key.size:
                raise ValueError("size mismatch {} {}".format(self.size,key.size))
            repMsg = generic_msg("[pdarray] {} {}".format(self.name, key.name))
            return create_pdarray(repMsg);
        else:
            return NotImplemented

    def __setitem__(self, key, value):
        if isinstance(key, int):
            if (key >= 0 and key < self.size):
                generic_msg("[int]=val {} {} {} {}".format(self.name, key, self.dtype.name, self.format_other(value)))
            else:
                raise IndexError("index {} is out of bounds with size {}".format(key,self.size))
        elif isinstance(key, pdarray):
            if isinstance(value, pdarray):
                generic_msg("[pdarray]=pdarray {} {} {}".format(self.name,key.name,value.name))
            else:
                generic_msg("[pdarray]=val {} {} {} {}".format(self.name, key.name, self.dtype.name, self.format_other(value)))
        elif isinstance(key, slice):
            (start,stop,stride) = key.indices(self.size)
            if v: print(start,stop,stride)
            if isinstance(value, pdarray):
                generic_msg("[slice]=pdarray {} {} {} {} {}".format(self.name,start,stop,stride,value.name))
            else:
                generic_msg("[slice]=val {} {} {} {} {} {}".format(self.name, start, stop, stride, self.dtype.name, self.format_other(value)))
        else:
            return NotImplemented

    def __iter__(self):
        # to_ndarray will error if array is too large to bring back
        a = self.to_ndarray()
        for x in a:
            yield x
            
    def fill(self, value):
        """
        Fill the array (in place) with a constant value.
        """
        generic_msg("set {} {} {}".format(self.name, self.dtype.name, self.format_other(value)))

    def any(self):
        """
        Return True iff any element of the array evaluates to True.
        """
        return any(self)
    
    def all(self):
        """
        Return True iff all elements of the array evaluate to True.
        """
        return all(self)

    def is_sorted(self):
        """
        Return True iff the array is monotonically non-decreasing.
        """
        return is_sorted(self)
    
    def sum(self):
        """
        Return the sum of all elements in the array.
        """
        return sum(self)
    
    def prod(self):
        """
        Return the product of all elements in the array. Return value is
        always a float.
        """
        return prod(self)
    
    def min(self):
        """
        Return the minimum value of the array.
        """
        return min(self)
    
    def max(self):
        """
        Return the maximum value of the array.
        """
        return max(self)
    
    def argmin(self):
        """
        Return the index of the first minimum value of the array.
        """
        return argmin(self)
    
    def argmax(self):
        """
        Return the index of the first maximum value of the array.
        """
        return argmax(self)
    
    def mean(self):
        """
        Return the mean of the array.
        """
        return mean(self)
    
    def var(self, ddof=0):
        """
        Compute the variance. See ``arkouda.var`` for details.
        """
        return var(self, ddof=ddof)
    
    def std(self, ddof=0):
        """
        Compute the standard deviation. See ``arkouda.std`` for details.
        """
        return std(self, ddof=ddof)

    def to_ndarray(self):
        """
        Convert the array to a np.ndarray, transferring array data from the
        arkouda server to Python. If the array exceeds a builtin size limit, 
        a RuntimeError is raised.

        Returns
        -------
        np.ndarray
            A numpy ndarray with the same attributes and data as the pdarray

        Notes
        -----
        The number of bytes in the array cannot exceed ``arkouda.maxTransferBytes``,
        otherwise a ``RuntimeError`` will be raised. This is to protect the user
        from overflowing the memory of the system on which the Python client
        is running, under the assumption that the server is running on a
        distributed system with much more memory than the client. The user
        may override this limit by setting ak.maxTransferBytes to a larger
        value, but proceed with caution.

        See Also
        --------
        array

        Examples
        --------
        >>> a = ak.arange(0, 5, 1)
        >>> a.to_ndarray()
        array([0, 1, 2, 3, 4])

        >>> type(a.to_ndarray())
        numpy.ndarray
        """
        # Total number of bytes in the array data
        arraybytes = self.size * self.dtype.itemsize
        # Guard against overflowing client memory
        if arraybytes > maxTransferBytes:
            raise RuntimeError("Array exceeds allowed size for transfer. Increase ak.maxTransferBytes to allow")
        # The reply from the server will be a bytes object
        rep_msg = generic_msg("tondarray {}".format(self.name), recv_bytes=True)
        # Make sure the received data has the expected length
        if len(rep_msg) != self.size*self.dtype.itemsize:
            raise RuntimeError("Expected {} bytes but received {}".format(self.size*self.dtype.itemsize, len(rep_msg)))
        # Use struct to interpret bytes as a big-endian numeric array
        fmt = '>{:n}{}'.format(self.size, structDtypeCodes[self.dtype.name])
        # Return a numpy ndarray
        return np.array(struct.unpack(fmt, rep_msg))

    def save(self, prefix_path, dataset='array', mode='truncate'):
        """
        Save the pdarray to HDF5. The result is a collection of HDF5 files,
        one file per locale of the arkouda server, where each filename starts
        with prefix_path. Each locale saves its chunk of the array to its
        corresponding file.

        Parameters
        ----------
        prefix_path : str
            Directory and filename prefix that all output files share
        dataset : str
            Name of the dataset to create in HDF5 files (must not already exist)
        mode : {'truncate' | 'append'}
            By default, truncate (overwrite) output files, if they exist.
            If 'append', attempt to create new dataset in existing files.

        See Also
        --------
        save_all, load, read_hdf, read_all

        Notes
        -----
        The prefix_path must be visible to the arkouda server and the user must have
        write permission.

        Output files have names of the form ``<prefix_path>_LOCALE<i>.hdf``, where ``<i>``
        ranges from 0 to ``numLocales``. If any of the output files already exist and
        the mode is 'truncate', they will be overwritten. If the mode is 'append'
        and the number of output files is less than the number of locales or a
        dataset with the same name already exists, a ``RuntimeError`` will result.

        Examples
        --------
        >>> a = ak.arange(0, 100, 1)
        >>> a.save('arkouda_range', dataset='array')

        Array is saved in numLocales files with names like ``tmp/arkouda_range_LOCALE0.hdf``

        The array can be read back in as follows

        >>> b = ak.load('arkouda_range', dataset='array')
        >>> (a == b).all()
        True
        """
        if mode.lower() in 'append':
            m = 1
        elif mode.lower() in 'truncate':
            m = 0
        else:
            raise ValueError("Allowed modes are 'truncate' and 'append'")
        rep_msg = generic_msg("tohdf {} {} {} {}".format(self.name, dataset, m, json.dumps([prefix_path])))


# creates pdarray object
#   only after:
#       all values have been checked by python module and...
#       server has created pdarray already befroe this is called
def create_pdarray(repMsg):
    """
    Return a pdarray instance pointing to an array created by the arkouda server.
    The user should not call this function directly.
    """
    fields = repMsg.split()
    name = fields[1]
    dtype = fields[2]
    size = int(fields[3])
    ndim = int(fields[4])
    shape = [int(el) for el in fields[5][1:-1].split(',')]
    itemsize = int(fields[6])
    if v: print("{} {} {} {} {} {}".format(name,dtype,size,ndim,shape,itemsize))
    return pdarray(name,dtype,size,ndim,shape,itemsize)

def info(pda):
    if isinstance(pda, pdarray):
        return generic_msg("info {}".format(pda.name))
    elif isinstance(pda, str):
        return generic_msg("info {}".format(pda))
    else:
        raise TypeError("info: must be pdarray or string {}".format(pda))
