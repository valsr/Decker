from .reducers import dot_reducer as dot_reducer, path_reducer as path_reducer, tuple_reducer as tuple_reducer, underscore_reducer as underscore_reducer
from .splitters import dot_splitter as dot_splitter, path_splitter as path_splitter, tuple_splitter as tuple_splitter, underscore_splitter as underscore_splitter
from _typeshed import Incomplete

REDUCER_DICT: Incomplete
SPLITTER_DICT: Incomplete

def flatten(d, reducer: str = 'tuple', inverse: bool = False, max_flatten_depth: Incomplete | None = None, enumerate_types=(), keep_empty_types=()): ...
def nested_set_dict(d, keys, value) -> None: ...
def unflatten(d, splitter: str = 'tuple', inverse: bool = False): ...
