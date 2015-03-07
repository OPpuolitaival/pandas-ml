#!/usr/bin/env python

import warnings

import numpy as np
import pandas as pd
import pandas.core.common as com
import pandas.compat as compat
from pandas.util.decorators import Appender, cache_readonly

from expandas.core.series import ModelSeries
from expandas.core.accessor import AccessorMethods
import expandas.skaccessors as skaccessors


_shared_docs = dict()


class ModelFrame(pd.DataFrame):
    """
    Data structure subclassing ``pandas.DataFrame`` to define a metadata to
    specify target (response variable) and data (explanatory variable / features).

    Parameters
    ----------
    data : same as ``pandas.DataFrame``
    target : str or array-like
        Column name or values to be used as target
    args : arguments passed to ``pandas.DataFrame``
    kwargs : keyword arguments passed to ``pandas.DataFrame``
    """

    _internal_names = (pd.core.generic.NDFrame._internal_names +
                       ['_target_name', '_estimator',
                        '_predicted', '_proba', '_log_proba', '_decision'])
    _internal_names_set = set(_internal_names)

    _mapper = dict(fit=dict(),
                   predict={'GaussianProcess': skaccessors.GaussianProcessMethods._predict})

    @property
    def _constructor(self):
        return ModelFrame

    _constructor_sliced = ModelSeries

    _TARGET_NAME = '.target'

    def __init__(self, data, target=None,
                 *args, **kwargs):

        if data is None and target is None:
            msg = '{0} must have either data or target'
            raise ValueError(msg.format(self.__class__.__name__))
        elif data is None and not com.is_list_like(target):
            msg = 'target must be list-like when data is None'
            raise ValueError(msg)

        try:
            from sklearn.datasets.base import Bunch
            if isinstance(data, Bunch):
                if target is not None:
                    raise ValueError
                # this should be first
                target = data.target
                # instanciate here to add column name
                columns = getattr(data, 'feature_names', None)
                data = pd.DataFrame(data.data, columns=columns)
        except ImportError:
            pass

        # retrieve target_name
        if isinstance(data, ModelFrame):
            target_name = data.target_name
        elif isinstance(target, pd.Series):
            target_name = target.name
            if target_name is None:
                target_name = self._TARGET_NAME
                target = pd.Series(target, name=target_name)
        else:
            target_name = self._TARGET_NAME

        data, target = self._maybe_convert_data(data, target, target_name, *args, **kwargs)

        if target is not None and not com.is_list_like(target):
            if target in data.columns:
                target_name = target
                df = data
            else:
                msg = "Specified target '{0}' is not included in data"
                raise ValueError(msg.format(target))
        else:
            df = self._concat_target(data, target)

        self._target_name = target_name
        self._estimator = None
        self._predicted = None
        self._proba = None
        self._log_proba = None
        self._decision = None

        pd.DataFrame.__init__(self, df, *args, **kwargs)

    def _maybe_convert_data(self, data, target, target_name, *args, **kwargs):
        """
        Internal function to instanciate data and target

        Parameters
        ----------
        data : instance converted to ``pandas.DataFrame``
        target : instance converted to ``pandas.Series``
        args : argument passed from ``__init__``
        kwargs : argument passed from ``__init__``
        """

        init_df = isinstance(data, pd.DataFrame)
        init_target = isinstance(target, pd.Series)

        if not init_df and not init_target:
            if data is not None:
                data = pd.DataFrame(data, *args, **kwargs)

            if com.is_list_like(target):
                if data is not None:
                    target = pd.Series(target, name=target_name, index=data.index)
                else:
                    target = pd.Series(target, name=target_name)
        elif not init_df:
            if data is not None:
                index = kwargs.pop('index', target.index)
                data = pd.DataFrame(data, index=index, *args, **kwargs)
        elif not init_target:
            if com.is_list_like(target):
                if data is not None:
                    target = pd.Series(target, name=target_name, index=data.index)
                else:
                    target = pd.Series(target, name=target_name)
        else:
            # no conversion required
            pass
        return data, target


    def _concat_target(self, data, target):
        if data is None and target is None:
            msg = '{0} must have either data or target'
            raise ValueError(msg.format(self.__class__.__name__))

        elif data is None:
            return target

        elif target is None:
            return data

        if len(data) != len(target):
            raise ValueError('data and target must have same length')

        if not data.index.equals(target.index):
            raise ValueError('data and target must have equal index')
        return pd.concat([target, data], axis=1)

    def has_data(self):
        """
        Return whether ``ModelFrame`` has data

        Returns
        -------
        has_data : bool
        """
        return len(self._data_columns) > 0

    @property
    def _data_columns(self):
        return pd.Index([c for c in self.columns if c != self.target_name])

    @property
    def data(self):
        """
        Return data (explanatory variable / features)

        Returns
        -------
        data : ``ModelFrame``
        """
        if self.has_data():
            return self.loc[:, self._data_columns]
        else:
            return None

    @data.setter
    def data(self, data):
        if data is None:
            del self.data
            return

        if isinstance(data, ModelFrame):
            if data.has_target():
                msg = 'Cannot update with {0} which has target attribute'
                raise ValueError(msg.format(self.__class__.__name__))

        data, _ = self._maybe_convert_data(data, self.target, self.target_name)

        if self.target_name in data.columns:
            msg = "Passed data has the same column name as the target '{0}'"
            raise ValueError(msg.format(self.target_name))

        if self.has_target():
            data = self._concat_target(data, self.target)
        self._update_inplace(data)

    @data.deleter
    def data(self):
        if self.has_target():
            self._update_inplace(self.target.to_frame())
        else:
            msg = '{0} must have either data or target'
            raise ValueError(msg.format(self.__class__.__name__))

    def has_target(self):
        """
        Return whether ``ModelFrame`` has target

        Returns
        -------
        has_target : bool
        """
        return self.target_name in self.columns

    @property
    def target_name(self):
        """
        Return target column name

        Returns
        -------
        target : object
        """
        return self._target_name

    @target_name.setter
    def target_name(self, value):
        self._target_name = value

    @property
    def target(self):
        """
        Return target (response variable)

        Returns
        -------
        target : ``ModelSeries``
        """
        if self.has_target():
            return self.loc[:, self.target_name]
        else:
            return None

    @target.setter
    def target(self, target):
        if target is None:
            del self.target
            return

        if not self.has_target():
            # allow to update target_name only when target attibute doesn't exist
            if isinstance(target, pd.Series):
                if target.name is not None:
                    self.target_name = target.name

        if not com.is_list_like(target):
            if target in self.columns:
                self.target_name = target
            else:
                msg = "Specified target '{0}' is not included in data"
                raise ValueError(msg.format(target))
            return

        if isinstance(target, pd.Series):
            if target.name != self.target_name:
                msg = "Passed data is being renamed to '{0}'".format(self.target_name)
                warnings.warn(msg)
                target = pd.Series(target, name=self.target_name)
        else:

            _, target = self._maybe_convert_data(self.data, target, self.target_name)

        df = self._concat_target(self.data, target)
        self._update_inplace(df)

    @target.deleter
    def target(self):
        if self.has_data():
            self._update_inplace(self.data)
        else:
            msg = '{0} must have either data or target'
            raise ValueError(msg.format(self.__class__.__name__))

    @property
    def estimator(self):
        """
        Return most recently used estimator

        Returns
        -------
        estimator : estimator
        """
        return self._estimator

    @estimator.setter
    def estimator(self, value):
        if not self._estimator is value:
            self._estimator = value
            # reset other properties
            self._predicted = None
            self._proba = None
            self._log_proba = None
            self._decision = None

    @property
    def predicted(self):
        """
        Return current estimator's predicted results

        Returns
        -------
        predicted : ``ModelSeries``
        """
        if self._predicted is None:
            self._predicted = self.predict(self.estimator)
            msg = "Automatically call '{0}.predict()'' to get predicted results"
            warnings.warn(msg.format(self.estimator.__class__.__name__))
        return self._predicted

    @property
    def proba(self):
        """
        Return current estimator's probabilities

        Returns
        -------
        probabilities : ``ModelFrame``
        """
        if self._proba is None:
            self._proba = self.predict_proba(self.estimator)
            msg = "Automatically call '{0}.predict_proba()' to get probabilities"
            warnings.warn(msg.format(self.estimator.__class__.__name__))
        return self._proba

    @property
    def log_proba(self):
        """
        Return current estimator's log probabilities

        Returns
        -------
        probabilities : ``ModelFrame``
        """
        if self._log_proba is None:
            self._log_proba = self.predict_log_proba(self.estimator)
            msg = "Automatically call '{0}.predict_log_proba()' to get log probabilities"
            warnings.warn(msg.format(self.estimator.__class__.__name__))
        return self._log_proba

    @property
    def decision(self):
        """
        Return current estimator's decision function

        Returns
        -------
        probabilities : ``ModelFrame``
        """
        if self._decision is None:
            self._decision = self.decision_function(self.estimator)
            msg = "Automatically call '{0}.decition_function()' to get decision function"
            warnings.warn(msg.format(self.estimator.__class__.__name__))
        return self._decision

    def _check_attr(self, estimator, method_name):
        if not hasattr(estimator, method_name):
            msg = "class {0} doesn't have {1} method"
            raise ValueError(msg.format(type(estimator), method_name))
        return getattr(estimator, method_name)

    def _get_mapper(self, estimator, method_name):
        if method_name in self._mapper:
            mapper = self._mapper[method_name]
        return mapper.get(estimator.__class__.__name__, None)

    def _call(self, estimator, method_name, *args, **kwargs):
        method = self._check_attr(estimator, method_name)

        data = self.data.values
        if self.has_target():
            target = self.target.values
            try:
                result = method(data, y=target, *args, **kwargs)
            except TypeError:
                result = method(data, *args, **kwargs)
        else:
            # not try to pass target if it doesn't exists
            # to catch ValueError from estimator
            result = method(data, *args, **kwargs)
        self.estimator = estimator
        return result

    _shared_docs['estimator_methods'] = """
        Call estimator's %(funcname)s method.

        Parameters
        ----------
        args : arguments passed to %(funcname)s method
        kwargs : keyword arguments passed to %(funcname)s method

        Returns
        -------
        %(returned)s
        """

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='fit', returned='returned : None or fitted estimator'))
    def fit(self, estimator, *args, **kwargs):
        return self._call(estimator, 'fit', *args, **kwargs)

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='predict', returned='returned : predicted result'))
    def predict(self, estimator, *args, **kwargs):
        mapped = self._get_mapper(estimator, 'predict')
        if mapped is not None:
            result = mapped(self, estimator, *args, **kwargs)
            # save estimator when succeeded
            self.estimator = estimator
            return result
        predicted = self._call(estimator, 'predict', *args, **kwargs)
        return self._wrap_predicted(predicted, estimator)

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='fit_predict', returned='returned : predicted result'))
    def fit_predict(self, estimator, *args, **kwargs):
        predicted = self._call(estimator, 'fit_predict', *args, **kwargs)
        return self._wrap_predicted(predicted, estimator)

    def _wrap_predicted(self, predicted, estimator):
        """
        Wrapper for predict methods
        """
        try:
            predicted = self._constructor_sliced(predicted, index=self.index)
        except ValueError:
            msg = "Unable to instantiate ModelSeries for '{0}'"
            warnings.warn(msg.format(estimator.__class__.__name__))
        self._predicted = predicted
        return self._predicted

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='predict_proba', returned='returned : probabilities'))
    def predict_proba(self, estimator, *args, **kwargs):
        probability = self._call(estimator, 'predict_proba', *args, **kwargs)
        self._proba = self._wrap_probability(probability, estimator)
        return self._proba

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='predict_log_proba', returned='returned : probabilities'))
    def predict_log_proba(self, estimator, *args, **kwargs):
        probability = self._call(estimator, 'predict_log_proba', *args, **kwargs)
        self._log_proba = self._wrap_probability(probability, estimator)
        return self._log_proba

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='decision_function', returned='returned : decisions'))
    def decision_function(self, estimator, *args, **kwargs):
        decision = self._call(estimator, 'decision_function', *args, **kwargs)
        self._decision = self._wrap_probability(decision, estimator)
        return self._decision

    def _wrap_probability(self, probability, estimator):
        """
        Wrapper for probability methods
        """
        try:
            if len(probability.shape) < 2 or probability.shape[1] == 1:
                # 2 class
                probability = self._constructor(probability, index=self.index)
            else:
                probability = self._constructor(probability, index=self.index,
                                                columns=estimator.classes_)
        except ValueError:
            msg = "Unable to instantiate ModelFrame for '{0}'"
            warnings.warn(msg.format(estimator.__class__.__name__))
        return probability

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='score', returned='returned : score'))
    def score(self, estimator, *args, **kwargs):
        score = self._call(estimator, 'score', *args, **kwargs)
        return score

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='transform', returned='returned : transformed result'))
    def transform(self, estimator, *args, **kwargs):
        transformed = self._call(estimator, 'transform', *args, **kwargs)
        return self._wrap_transform(transformed)

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='fit_transform', returned='returned : transformed result'))
    def fit_transform(self, estimator, *args, **kwargs):
        transformed = self._call(estimator, 'fit_transform', *args, **kwargs)
        return self._wrap_transform(transformed)

    def _wrap_transform(self, transformed):
        """
        Wrapper for transform methods
        """
        if self.has_target():
            return self._constructor(transformed, target=self.target, index=self.index)
        else:
            return self._constructor(transformed, index=self.index)

    @Appender(_shared_docs['estimator_methods'] %
              dict(funcname='inverse_transform', returned='returned : transformed result'))
    def inverse_transform(self, estimator, *args, **kwargs):
        transformed = self._call(estimator, 'inverse_transform', *args, **kwargs)
        return self._wrap_transform(transformed)

    @cache_readonly
    def cluster(self):
        """Property to access ``sklearn.cluster``"""
        return skaccessors.ClusterMethods(self)

    @cache_readonly
    def covariance(self):
        """Property to access ``sklearn.covariance``"""
        return skaccessors.CovarianceMethods(self)

    @cache_readonly
    def cross_decomposition(self):
        """Property to access ``sklearn.cross_decomposition``"""
        attrs = ['PLSRegression', 'PLSCanonical', 'CCA', 'PLSSVD']
        return AccessorMethods(self, module_name='sklearn.cross_decomposition',
                               attrs=attrs)

    @cache_readonly
    def cross_validation(self):
        """Property to access ``sklearn.cross_validation``"""
        return skaccessors.CrossValidationMethods(self)

    @property
    def crv(self):
        """Property to access ``sklearn.cross_validation``"""
        return self.cross_validation

    @cache_readonly
    def decomposition(self):
        """Property to access ``sklearn.decomposition``"""
        return skaccessors.DecompositionMethods(self)

    @cache_readonly
    def dummy(self):
        """Property to access ``sklearn.dummy``"""
        attrs = ['DummyClassifier', 'DummyRegressor']
        return AccessorMethods(self, module_name='sklearn.dummy', attrs=attrs)

    @cache_readonly
    def ensemble(self):
        """Property to access ``sklearn.ensemble``"""
        return skaccessors.EnsembleMethods(self)

    @cache_readonly
    def feature_extraction(self):
        """Property to access ``sklearn.feature_extraction``"""
        return skaccessors.FeatureExtractionMethods(self)

    @cache_readonly
    def feature_selection(self):
        """Property to access ``sklearn.feature_selection``"""
        return skaccessors.FeatureSelectionMethods(self)

    @cache_readonly
    def gaussian_process(self):
        """Property to access ``sklearn.gaussian_process``"""
        return skaccessors.GaussianProcessMethods(self)

    @cache_readonly
    def grid_search(self):
        """Property to access ``sklearn.grid_search``"""
        return skaccessors.GridSearchMethods(self)

    @cache_readonly
    def isotonic(self):
        """Property to access ``sklearn.isotonic``"""
        return skaccessors.IsotonicMethods(self)

    @cache_readonly
    def kernel_approximation(self):
        """Property to access ``sklearn.kernel_approximation``"""
        attrs = ['AdditiveChi2Sampler', 'Nystroem', 'RBFSampler', 'SkewedChi2Sampler']
        return AccessorMethods(self, module_name='sklearn.kernel_approximation',
                               attrs=attrs)

    @cache_readonly
    def lda(self):
        """Property to access ``sklearn.lda``"""
        return AccessorMethods(self, module_name='sklearn.lda')

    @cache_readonly
    def linear_model(self):
        """Property to access ``sklearn.linear_model``"""
        return skaccessors.LinearModelMethods(self)

    @cache_readonly
    def manifold(self):
        """Property to access ``sklearn.manifold``"""
        return skaccessors.ManifoldMethods(self)

    @cache_readonly
    def mixture(self):
        """Property to access ``sklearn.mixture``"""
        return AccessorMethods(self, module_name='sklearn.mixture')

    @cache_readonly
    def metrics(self):
        """Property to access ``sklearn.metrics``"""
        return skaccessors.MetricsMethods(self)

    @cache_readonly
    def multiclass(self):
        """Property to access ``sklearn.multiclass``"""
        return skaccessors.MultiClassMethods(self)

    @cache_readonly
    def naive_bayes(self):
        """Property to access ``sklearn.naive_bayes``"""
        return AccessorMethods(self, module_name='sklearn.naive_bayes')

    @cache_readonly
    def neighbors(self):
        """Property to access ``sklearn.neighbors``"""
        return skaccessors.NeighborsMethods(self)

    @cache_readonly
    def pipeline(self):
        """Property to access ``sklearn.pipeline``"""
        return skaccessors.PipelineMethods(self)

    @cache_readonly
    def preprocessing(self):
        """Property to access ``sklearn.preprocessing``"""
        return skaccessors.PreprocessingMethods(self)

    @property
    def pp(self):
        """Property to access ``sklearn.preprocessing``"""
        return self.preprocessing

    @cache_readonly
    def qda(self):
        """Property to access ``sklearn.qda``"""
        return AccessorMethods(self, module_name='sklearn.qda')

    @cache_readonly
    def semi_supervised(self):
        """Property to access ``sklearn.semi_supervised``"""
        return AccessorMethods(self, module_name='sklearn.semi_supervised')

    @cache_readonly
    def svm(self):
        """Property to access ``sklearn.svm``"""
        return skaccessors.SVMMethods(self)

    @cache_readonly
    def tree(self):
        """Property to access ``sklearn.tree``"""
        return AccessorMethods(self, module_name='sklearn.tree')

