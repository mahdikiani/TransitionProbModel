#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wrapper for different types of Ideal Observers:
    - The hidden markov model for coupled change points, with known volatility
    - The hidden markov model for coupled change points and unknown volatility
    - he hidden markov model for uncoupled change points, with known volatility
    - he hidden markov model for uncoupled change points and unknown volatility
    - The fixed Bayesian observer model ("window" and "decay")

To do next:
allow the user to change the prior, at least in the leaky case

@author: Florent Meyniel
"""

import itertools

from . import Inference_NoChangePoint as io_fixed
from . import Inference_ChangePoint as io_hmm
from . import Inference_UncoupledChangePoint as io_hmm_unc
from . import inference_volatility as io_hmm_vol
from . import inference_uncoupled_volatility as io_hmm_uncoupled_vol

import numpy as np
from scipy.stats import dirichlet
from scipy import special


def IdealObserver(seq, ObsType, order=0, Nitem=None, options=None):
    """
    IdealObserver is a wrapper that computes the posterior inference of generative
    probabilities of the sequence seq.
    - seq is the sequence (numpy array, see GenerateSequence.ConvertSequence)
    - ObsType is either 'Decay', 'window', 'hmm', 'hmm_uncoupled', 'hmm+full' or
      'hmm_uncoupled+full' (see Examples.py)
    - order is the order of transition probabilities
    - Nitem is the size of alphabet (maximum number of different items in the sequence)
    - options is a dictionary
      'p_c': a priori volatility (for hmm)
      'resol': number of bins used for discretization (for hmm)
      'prior_weight': the weight of the prior (which is unbiased)
    """

    options = check_options(options)

    if Nitem is None:
        Nitem = len(set(seq))

    if ObsType.lower() == 'fixed':
        options['order'] = order
        options['Nitem'] = Nitem
        prior = parse_options(options, 'fixed_prior')
        Decay, Window = parse_options(options, 'fixed_type')

        # Get posterior
        count = io_fixed.count_tuple(
            seq, order=order, Nitem=Nitem, Decay=Decay, Window=Window)
        post = io_fixed.posterior_no_jump(
            count=count, prior=prior, Nitem=Nitem, order=order)

        # Fill output
        out = {}
        for item in post['mean'].keys():
            out[item] = {}
            out[item]['mean'] = post['mean'][item]
            out[item]['MAP'] = post['MAP'][item]
            out[item]['SD'] = post['SD'][item]
        out['surprise'] = compute_surprise(seq, out, order)
        out['count'] = count
        out['alphas'] = compute_alpha(seq, out, order, prior, Nitem)
        out['shannon'] = out['surprise']
        out['bayesian'] = compute_bayesian(out)
        out['confidence-corrected'] = compute_confidence_corrected(out, Nitem)

    if ObsType.lower() == 'hmm':
        resol, p_c = parse_options(options, 'hmm_param')

        # Get full posterior
        marg_post = io_hmm.compute_inference(seq=seq, resol=resol,
                                             order=order, Nitem=Nitem, p_c=p_c)

        # Fill output
        out = fill_output_hmm(marg_post, resol, Nitem)
        out['surprise'] = compute_surprise(seq, out, order)

    if ObsType.lower() == 'hmm_uncoupled':
        resol, p_c = parse_options(options, 'hmm_param')

        # Re-code the sequence for each type of transition
        conv_seq = io_hmm_unc.convert_to_order0(
            seq=seq, Nitem=Nitem, order=order)

        # Get full posterior
        # Treat the different transition types independently from one another (since their change
        # points are not coupled)
        marg_post = {}
        for cond in conv_seq.keys():
            post_all_items = io_hmm_unc.compute_inference(
                seq=conv_seq[cond],
                resol=resol, Nitem=Nitem, p_c=p_c)
            for item in post_all_items.keys():
                marg_post[cond+item] = post_all_items[item]

        # Fill output
        out = fill_output_hmm(marg_post, resol, Nitem)
        out['surprise'] = compute_surprise(seq, out, order)

    if ObsType.lower() == 'hmm+full':
        theta_resol, vol_grid, vol_prior = parse_options(options, 'hmm+full')
        res = io_hmm_vol.posterior_prediction(
            seq, order, Nitem, theta_resol, vol_grid, vol_prior)

        # Fill output
        out = fill_output_hmm(res['marg_theta'], theta_resol, Nitem)
        out['surprise'] = compute_surprise(seq, out, order)
        out['volatility'] = res['post_nu']

    if ObsType.lower() == 'hmm_uncoupled+full':
        theta_resol, vol_grid, vol_prior = parse_options(options, 'hmm+full')
        res = io_hmm_uncoupled_vol.posterior_prediction(
            seq, order, Nitem, theta_resol, vol_grid, vol_prior)

        # Fill output
        out = fill_output_hmm(res['marg_theta'], theta_resol, Nitem)
        out['surprise'] = compute_surprise(seq, out, order)
        out['volatility'] = res['post_nu']

    out = add_predictions(out, seq, order, options, ObsType, Nitem)
    return out


def parse_options(options, key):
    """
    Parse options
    """
    if key == 'fixed_type':
        if 'decay' in options.keys():
            Decay, Window = options['decay'], None
        elif 'window' in options.keys():
            Decay, Window = None, options['window']
        else:
            Decay, Window = None, None
        return Decay, Window

    elif key == 'hmm_param':
        if 'resol' in options.keys():
            resol = options['resol']
        else:
            resol = 10
        if 'p_c' in options.keys():
            p_c = options['p_c']
        else:
            raise ValueError('options should contain a key "p_c"')
        return resol, p_c
    elif key == 'hmm+full':
        if 'resol' in options.keys():
            resol = options['resol']
        else:
            resol = 10
        if 'grid_nu' in options.keys():
            grid_nu = options['grid_nu']
            if 'prior_nu' in options.keys():
                prior_nu = options['prior_nu']
            else:
                prior_nu = np.ones(len(grid_nu))/len(grid_nu)
        else:
            grid_nu = 1/2 ** np.array([k/2 for k in range(20)])
            prior_nu = np.ones(len(grid_nu))/len(grid_nu)
        return resol, grid_nu, prior_nu
    elif key == 'fixed_prior':
        if 'prior_weight' in options.keys():
            prior = io_fixed.symetric_prior(order=options['order'],
                                            Nitem=options['Nitem'],
                                            weight=options['prior_weight'])
        elif 'custom_prior' in options.keys():
            prior = options['custom_prior']
        else:
            prior = io_fixed.symetric_prior(order=options['order'],
                                            Nitem=options['Nitem'], weight=1)
        return prior
    else:
        return None


def check_options(options):
    checked_options = {}

    # use lower case for all options
    for item in options.keys():
        checked_options[item.lower()] = options[item]
    return checked_options


def compute_mean_of_dist(dist, pgrid):
    """ Compute mean of probability distribution"""
    return dist.transpose().dot(pgrid)


def compute_sd_of_dist(dist, pgrid, Nitem):
    """ Compute SD of probability distribution"""
    m = compute_mean_of_dist(dist, pgrid)
    v = dist.transpose().dot(pgrid**2) - m**2
    return np.sqrt(v)


def compute_surprise(seq, out, order):
    """
    Compute surprise, conditional on the specified order
    """
    surprise = np.nan * np.ones(len(seq))
    patterns = set(out.keys())
    if order == 0:
        for t in range(1, len(seq)):
            if (seq[t],) in patterns:
                surprise[t] = -np.log2(out[(seq[t],)]['mean'][t-1])
    else:
        for t in range(order, len(seq)):
            if tuple(seq[t-order:t+1]) in patterns:
                surprise[t] = - \
                    np.log2(out[tuple(seq[t-order:t+1])]['mean'][t-1])
    return surprise


def compute_alpha(seq, out, order, prior, Nitem=None):
    """
    Compute Dirichlet parameter, conditional on the specified order
    """
    if Nitem is None:
        Nitem = len(set(seq))

    priors = list(itertools.product(range(Nitem), repeat=order))

    # alphas = np.nan * np.ones((len(seq), priors.shape[0], Nitem))
    alphas = {p: np.nan * np.ones((len(seq), Nitem)) for p in priors}

    for p, s in itertools.product(priors, range(Nitem)):
        item = p + (s, )
        alphas[p][:, s] = out['count'][item] + prior[item]

    return alphas


def compute_bayesian(out):
    return KL(out['alphas'])


def compute_confidence_corrected(out, Nitem):
    p_hat = {2: 1/2, 3: 1/24}
    S_raw = out['shannon'] + out['bayesian'] - H0(out['alphas'])
    S_corr = S_raw + np.log(p_hat[Nitem])
    return S_corr


def fill_output_hmm(post, resol, Nitem):
    """
    Fill output strucutre of hmm inferece
    """
    out = {}
    pgrid = np.linspace(0, 1, resol)
    for item in post.keys():
        out[item] = {}
        out[item]['dist'] = post[item]
        out[item]['mean'] = compute_mean_of_dist(post[item], pgrid)
        out[item]['SD'] = compute_sd_of_dist(post[item], pgrid, Nitem)
    return out


def add_predictions(out, seq, order, options, ObsType, Nitem):
    """
    Add two types of prediction on trial k:
        - the prior prediction, about the stimulus presented on this trial k (i.e. given all
          obervations, k included), and the associated confidence.
        - the current prediction, about the stimulus presented on the next trial, k+1 (i.e. given
          all previous observations, k included), and the associated confidence.
    The prediction is the probability of observing item 0. The current code is for binary
    sequences only
    """
    if Nitem > 2:
        out['current_prediction_p0'] = None
        out['current_prediction_SDp0'] = None
        out['prior_prediction_p0'] = None
        out['prior_prediction_SDp0'] = None
    else:
        # Get the prior
        if order == 0:
            if ObsType.lower() == 'fixed':
                prior = parse_options(options, 'fixed_prior')
                Dirichlet_param = [prior[(0,)], prior[(1,)]]
            else:
                # For the other observers, the current code assumes a flat prior (this could be
                # changed in the future)
                Dirichlet_param = [1, 1]
        else:
            # Assume that the 1st element of a sequence is selected uniformly from the set of
            # possible items (this is what the Ideal observer implemented here does).
            # Another solution could have been to use the transition probabilities to compute the
            # base rate of each item and use it as a prior.
            Dirichlet_param = [1, 1]
        prior_p0 = dirichlet.mean(Dirichlet_param)[0]
        prior_SDp0 = np.sqrt(dirichlet.var(Dirichlet_param)[0])

        # convert the sequence to a list for convenience
        seq = list(seq)

        # Get current prediction
        out['current_prediction_p0'] = prior_p0 * np.ones(len(seq))
        out['current_prediction_SDp0'] = prior_SDp0 * np.ones(len(seq))
        if order == 0:
            for t in range(len(seq)):
                out['current_prediction_p0'][t] = out[(0,)]['mean'][t]
                out['current_prediction_SDp0'][t] = out[(0,)]['SD'][t]
        else:
            for t in range(order, len(seq)):
                if any(np.array(seq[t-order+1:t+1]) == Nitem):
                    # By convention, an item whose value is Nitem corresponds to a pause
                    out['current_prediction_p0'][t] = prior_p0
                    out['current_prediction_SDp0'][t] = prior_SDp0
                else:
                    out['current_prediction_p0'][t] = out[tuple(
                        seq[t-order+1:t+1]+[0])]['mean'][t]
                    out['current_prediction_SDp0'][t] = out[tuple(
                        seq[t-order+1:t+1]+[0])]['SD'][t]

        # Get prior prediction
        out['prior_prediction_p0'] = prior_p0 * np.ones(len(seq))
        out['prior_prediction_SDp0'] = prior_SDp0 * np.ones(len(seq))
        out['prior_prediction_p0'][1:] = out['current_prediction_p0'][:-1]
        out['prior_prediction_SDp0'][1:] = out['current_prediction_SDp0'][:-1]

    return out


def KL_dirichlet(alpha: np.ndarray, beta: np.ndarray) -> float:
    '''
    d = KL_dirichlet(alpha, beta) calculates the Kullback-Leibler divergence
    between two Dirichlet distributions with parameters alpha and beta
    respectively. It is assumed that the parameters are valid, that is
    alpha[i] > 0 and beta[i] > 0 for all i = 1:alpha.shape[0]

    Inputs:
        alpha: parameters of the first Dirichlet distribution
        beta: parameters of the second Dirichlet distribution

    Output:
        - d: the KL divergence.

    Reference:
        https://statproofbook.github.io/P/dir-kl.html

    Date: 12 July 2022

    Mahdi Kiani
    Sharif University of Technology, Dept. of Electrical Engineering
    mahdikiany@gmail.com
    '''

    assert alpha.ndim == 1
    assert alpha.shape == beta.shape
    assert np.all(alpha > 0) and np.all(beta > 0)

    d = special.gammaln(alpha.sum()) - special.gammaln(beta.sum()) + \
        special.gammaln(beta).sum() - special.gammaln(alpha).sum() + \
        np.dot(alpha - beta, special.psi(alpha) - special.psi(alpha.sum()))

    return d


def KL(alphas):
    '''
    Note: KL is additive for independent distributions.
    '''

    KL = np.nan * np.ones((len(list(alphas.keys())),
                           list(alphas.values())[0].shape[0]))
    for i, alpha in enumerate(alphas.values()):
        for j in range(1, alpha.shape[0]):
            KL[i, j] = KL_dirichlet(alpha[j-1, :], alpha[j, :])

    return KL.sum(axis=0)


def H0(alphas):
    '''
    Note: H0 is additive for independent distributions.
    '''

    h0 = np.nan * np.ones((len(list(alphas.keys())),
                           list(alphas.values())[0].shape[0]))
    for i, alpha in enumerate(alphas.values()):
        for j in range(alpha.shape[0]):
            h0[i, j] = dirichlet.entropy(alpha[j, :])

    return h0.sum(axis=0)
