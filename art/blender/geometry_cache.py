"""Build-local memoisation of pure rings, with independent mutable results for callers."""
from functools import wraps
from inspect import signature


_caches = []


def freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((key, freeze(item)) for key, item in value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(map(freeze, value))
    if isinstance(value, float):
        return (float, value.hex())
    return value


def clear():
    for cache in _caches:
        cache.clear()


def ring(function):
    cache = {}
    _caches.append(cache)
    parameters = signature(function)

    @wraps(function)
    def memoised(*args, **kwargs):
        bound = parameters.bind(*args, **kwargs)
        bound.apply_defaults()
        key = freeze(bound.arguments)
        if key not in cache:
            cache[key] = tuple(v.copy() for v in function(*args, **kwargs))
        return [v.copy() for v in cache[key]]

    return memoised
