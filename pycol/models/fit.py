# -*- coding: utf-8 -*-
"""
pycol.models.fit

Created on 06.05.2023

@author: Patrick Mueller

Module to fit the models to data.
"""

import numpy as np

from pycol.types import *
from pycol.tools import asarray_optional, print_colored, print_cov
# noinspection PyUnresolvedReferences
from pycol.analyze import curve_fit, odr_fit
from pycol.models import base, helper


ROUTINES = {'curve_fit', 'odr_fit'}


class Xlist:  # Custom list to trick 'curve_fit' for linked fitting of files with different x-axis sizes.
    def __init__(self, x):
        self.x = x

    def __iter__(self):
        for _x in self.x:
            yield _x

    def __getitem__(self, key):
        return self.x[key]

    def __setitem__(self, key, value):
        self.x[key] = value


def residuals(model, x, y):
    return y - model(x, *model.vals)


def reduced_chi2(model, x, y, sigma_y):
    fixed, bounds = model.fit_prepare()
    n_free = sum(int(not f) for f in fixed)
    return np.sum(residuals(model, x, y) ** 2 / sigma_y ** 2) / (y.size - n_free)


def fit(model: base.Model, x: array_iter, y: array_iter, sigma_x: array_iter = None, sigma_y: array_iter = None,
        report: bool = False, routine: Union[Callable, str] = None, guess_offset: bool = False,
        mc_sigma: int = 0, **kwargs):
    """
    :param model: The model to fit.
    :param x: The x data. Can be any object accepted by the model.
     If model is a Linked model, x should be a list of objects compatible with the linked models.
    :param y: The y data. This has to be a 1-d array or a list of 1-d arrays if model is a Linked model.
    :param sigma_x: The uncertainties of the x-values. This is only compatible with Monte-Carlo sampling and the
     odr_fit routine. If sigma_x is not None, no routine is specified and mc_sigma == 0, the routine is automatically
     set to odr_fit.
    :param sigma_y: The uncertainties of the y-values.
     This has to be a 1-d array or a list of 1-d arrays if model is a Linked model and have the same shape as 'y'.
    :param report: Whether to print the fit results.
    :param routine: The routine to use for fitting. Currently supported are {curve_fit, odr_fit}.
     If None, curve_fit is used. See 'sigma_x' for one exception.
    :param guess_offset: Guess initial parameters for Offset models.
     Currently, this is not working if x is not a 1d-array.
    :param mc_sigma: The number of samples to generate from the data. If it is 0, no Monte-Carlo sampling will be done.
     This is not available with linked fitting.
    :param kwargs: Additional kwargs to pass to the fit 'routine'.
    :returns: The optimized parameters their covariance matrix and a dictionary containing info about the fit.
    :raises (ValueError, TypeError):
    """

    if routine is None:
        routine = odr_fit if sigma_x is not None and mc_sigma == 0 else curve_fit
    if isinstance(routine, str) and routine in ROUTINES:
        routine = eval(routine)
    if routine.__name__ not in ROUTINES:
        raise ValueError('Specified routine \'{}\' is not supported.'.format(routine.__name__))

    if not isinstance(model, base.Model):
        raise TypeError('\'model\' must have or inherit type pycol.models.Model but has type {}.'.format(type(model)))
    if model.error:
        raise ValueError(model.error)

    if isinstance(model, base.Linked):
        if mc_sigma != 0:
            raise TypeError('Linked models are currently not supported with Monte-Carlo sampling.')
        models_offset = helper.find_models(model, base.Offset)
        for _offset, _x, _y in zip(models_offset, x, y):
            if _offset is not None:
                _offset.update_on_call = False
                _offset.gen_offset_masks(_x)
                if guess_offset:
                    _offset.guess_offset(_x, _y)
        model.inherit_vals()
        x = Xlist(x)
        y = np.concatenate(y, axis=0)
        if sigma_x is not None:
            sigma_x = np.concatenate(sigma_x, axis=0)
        if sigma_y is not None:
            sigma_y = np.concatenate(sigma_y, axis=0)
    else:
        y = np.asarray(y, dtype=float)
        sigma_x, sigma_y = asarray_optional(sigma_x, dtype=float), asarray_optional(sigma_y, dtype=float)

        models_offset = [helper.find_model(model, base.Offset)]
        if models_offset[0] is not None:
            if models_offset[0] is not None:
                models_offset[0].update_on_call = False
                models_offset[0].gen_offset_masks(x)
                if guess_offset:
                    models_offset[0].guess_offset(x, y)

    p0_fixed, bounds = model.fit_prepare()

    kwargs.update({'report': False})
    if routine.__name__ == 'curve_fit':
        kwargs.update({'bounds': bounds, 'sigma': sigma_y})
    if routine.__name__ == 'odr_fit':
        kwargs.update({'sigma_x': sigma_x, 'sigma_y': sigma_y})

    err = False
    warn = False
    e = None
    try:
        if mc_sigma:
            kwargs['sigma'] = None
            kwargs['absolute_sigma'] = False
            kwargs['sigma_x'] = None
            kwargs['sigma_y'] = None
            if routine.__name__ == 'curve_fit':
                del kwargs['sigma_x'], kwargs['sigma_y']
            if routine.__name__ == 'odr_fit':
                del kwargs['sigma'], kwargs['absolute_sigma']

            if sigma_x is None:
                x_samples = [x, ] * mc_sigma
            else:
                x_samples = np.random.normal(loc=x, scale=sigma_x, size=(mc_sigma, ) + x.shape)
            if sigma_y is None:
                y_samples = [y, ] * mc_sigma
            else:
                y_samples = np.random.normal(loc=y, scale=sigma_y, size=(mc_sigma, ) + y.shape)

            pt = np.array([routine(model, x_sample, y_sample, p0=model.vals, p0_fixed=p0_fixed, **kwargs)[0]
                           for x_sample, y_sample in zip(x_samples, y_samples)], dtype=float)
            popt = np.mean(pt, axis=0)
            pcov = np.zeros((popt.size, popt.size))
            indices = np.array([i for i, fix in enumerate(p0_fixed) if not fix])
            mask = (indices[:, None], indices)
            pcov[mask] = np.cov(pt[:, indices], rowvar=False)
        else:
            popt, pcov = routine(model, x, y, p0=model.vals, p0_fixed=p0_fixed, **kwargs)
        popt = np.array(model.update_args(popt))
        model.set_vals(popt, force=True)
        chi2 = 0. if sigma_y is None else reduced_chi2(model, x, y, sigma_y)
    except (ValueError, RuntimeError) as _e:
        warn = True
        err = True
        chi2 = 0.
        popt = np.array(model.vals, dtype=float)
        pcov = np.zeros((popt.size, popt.size))
        e = _e

    if report:
        digits = int(np.floor(np.log10(np.abs(model.size)))) + 1
        print('Optimized parameters:')
        for j, (name, val, unc) in enumerate(zip(model.names, popt, np.sqrt(np.diag(pcov)))):
            print('{}:   {} = {} +/- {}'.format(str(j).zfill(digits), name, val, unc))
        print('\nCov. Matrix:')
        print_cov(pcov, normalize=True, decimals=2)
        print('\nRed. chi2 = {}'.format(np.around(chi2, decimals=2)))

        if err:
            print_colored('FAIL', 'Error while fitting: {}\n'.format(e))
        elif np.any(np.isinf(pcov)):
            warn = True
            print_colored('WARNING', 'Failed to estimate uncertainties.\n')
        else:
            print_colored('OKGREEN', 'Fit successful.\n')

    if isinstance(model, base.Linked):
        for model_offset in models_offset:
            model_offset.update_on_call = True  # Reset the offset model to be updated on call.
    else:
        if models_offset[0] is not None:
            models_offset[0].update_on_call = True  # Reset the offset model to be updated on call.

    info = dict(warn=warn, err=err, chi2=chi2)
    return popt, pcov, info
