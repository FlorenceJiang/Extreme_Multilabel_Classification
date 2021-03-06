# coding: utf-8

import numpy as np
import implicit # library that implements ALS model
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.linear_model import Ridge, Lasso, ElasticNet
from sklearn.neighbors.graph import kneighbors_graph
from sklearn.neighbors import NearestNeighbors
from collections import namedtuple
from ensemble import Model, Ensemble
from helpers import precision_at_ks, print_hdf5_object, project
from core import learn_V
import numpy as np
from sklearn.metrics import label_ranking_average_precision_score
from tqdm import tqdm


def main():
    # parameters from paper
    params = namedtuple('args', ['num_learner', 'num_clusters',
                                 'num_threads', 'SVP_neigh', 'out_dim',
                                 'w_thresh', 'sp_thresh', 'cost',
                                 'NNtest', 'normalize'])
    params.num_learners = 1  # 1
    params.num_clusters = 1  # 1
    params.num_threads = 32
    params.SVP_neigh = 250
    params.out_Dim = 100
    params.w_thresh = 0.01  # ?
    params.sp_thresh = 0.01  # ?
    params.NNtest = 25
    params.normalize = 1  # ?
    params.regressor_lambda1 = 1e-6
    params.regressor_lambda2 = 1e-3
    params.embedding_lambda = 0.1  # determined automatically in WAltMin_asymm.m


    train_X, train_Y, test_X, test_Y = load_input()


    clusterings = []
    for i in range(params.num_learners):
        model = KMeans(n_clusters=params.num_clusters, n_jobs=-1, n_init=8, max_iter=100)
        model.fit(train_X)
        clusterings.append(model)


    learners = []
    for clus_model in tqdm(clusterings):
        models = []
        for i in range(clus_model.n_clusters):
            # for each cluster in each learner
            # learn a model

            data_idx = np.nonzero(clus_model.labels_ == i)[0]
            X = train_X[data_idx, :]
            Y = train_Y[data_idx, :]

            print('embedding learning: building kNN graph')
            # build the kNN graph
            graph = kneighbors_graph(Y, params.SVP_neigh, mode='distance', metric='cosine',
                                     include_self=True,
                                     n_jobs=-1)
            graph.data = 1 - graph.data  # convert to similarity

            print('embedding learning: ALS')
            # learn the local embedding
            als_model = implicit.als.AlternatingLeastSquares(factors=params.out_Dim,
                                                             regularization=params.embedding_lambda)
            als_model.fit(graph)

            # the embedding
            # shape: #instances x embedding dim
            Z = als_model.item_factors

            print('linear regressor training')
            # learn the linear regressor
            if True:
                # regressor = Ridge(fit_intercept=True, alpha=params.regressor_lambda2)
                regressor = ElasticNet(alpha=0.1, l1_ratio=0.001)
                regressor.fit(X, Z)
                # shape: embedding dim x feature dim
                V = regressor.coef_
            else:
                # learn V with l2 on V and l1 on VX
                ## note that X is sparse
                V = learn_V(X.toarray(), Z,
                            lambda1=params.regressor_lambda1,
                            lambda2=params.regressor_lambda2,
                            iter_max=200,
                            print_log=True)
            # the nearest neighbour model
            fitted_Z = X.toarray() @ V.T

            Z_neighbors = NearestNeighbors(n_neighbors=params.NNtest,
                                           algorithm='kd_tree').fit(fitted_Z)

            projected_center = project(V, clus_model.cluster_centers_[i])
            learned = {
                'center_z': projected_center,
                'V': V,
                'Z_neighbors': Z_neighbors,
                'data_idx': data_idx
            }
            models.append(learned)
        learners.append(models)


    models = [Model(learner, train_Y)
              for learner in learners]
    ensemble = Ensemble(models)


    # predict
    pred_Y = ensemble.predict_many(test_X)
    performance = precision_at_ks(test_Y, pred_Y)


    # evaluation
    # precision@k
    for k, s in performance.items():
        print('precision@{}: {:.4f}'.format(k, s))
    # LRAP
    print(label_ranking_average_precision_score(test_Y.toarray(), pred_Y))


if __name__ == '__main__':
    main()