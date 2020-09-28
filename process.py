import glob
import os
import pickle

import networkx as nx
import numpy as np

from classifier import Classifier
from utils import establish_training_G, load_graph, load_training_data, load_test_data, build_graph
from support.Text2vec import sentence_emb
from support.Node2vec import node2vec_emb


def model_eval(original_G_path, content_emb_path, model_iter):
    preprocess(evaluate=True, bg=False)
    comp_helper(original_G_path=original_G_path,
                structural_emb_path=glob.glob(os.path.abspath('data/embedding/*.csv')),
                content_emb_path=content_emb_path, classifier='MLP', model_iter=model_iter)


def model_pred(original_G_path, content_emb_path, model_iter):
    preprocess(evaluate=False, bg=False)
    process(original_G_path=original_G_path,
            structural_emb_path=os.path.abspath('data/embedding/CrossNELP.csv'),
            content_emb_path=content_emb_path, classifier='MLP', pred=True, model_iter=model_iter, re_build_g=False)


def preprocess(evaluate, bg):
    # build network, ensure network exist before embedding
    build_graph(bg)

    if not os.path.exists(os.path.abspath('data/embedding/sentence_embedding/sentence_embedding.pkl')):
        print("In getting content embeddings")
        # content embedding
        sentence_emb.edge_content_emb()
        sentence_emb.node_content_emb()

    # structural embedding
    if evaluate:
        print("network embedding...")
        if not os.path.exists(os.path.abspath('data/embedding/CrossNELP.csv')):
            node2vec_emb.node_structure_emb('weighted', dim=128, walk_len=6, num_walks=80, p=1, q=0.5)
        if not os.path.exists(os.path.abspath('data/embedding/Node2Vec.csv')):
            node2vec_emb.node_structure_emb('unweighted', dim=128, walk_len=6, num_walks=80)
            os.chdir('support')
            os.system(
                "python -m openne --method deepWalk --input ../data/embedding/adjlist.txt --network-format adjlist --walk-length 6 --number-walks 80 --output ../data/embedding/Deepwalk.csv")
            os.system(
                "python -m openne --method line --input ../data/embedding/adjlist.txt --network-format adjlist --output ../data/embedding/LINE.csv")
            os.system(
                "python -m openne --method sdne --input ../data/embedding/adjlist.txt --network-format adjlist --output ../data/embedding/SDNE.csv")
            os.system(
                "python -m openne --method gf --input ../data/embedding/adjlist.txt --network-format adjlist --output ../data/embedding/GF.csv")
            os.chdir('../')
        print("network embedding finished")

    else:
        if not os.path.exists(os.path.abspath('data/embedding/CrossNELP.csv')):
            node2vec_emb.node_structure_emb('weighted', dim=128, walk_len=6, num_walks=80, p=1, q=0.5)


def process(original_G_path, structural_emb_path, content_emb_path, classifier, pred, model_iter, re_build_g):
    binding = []
    infection = ''
    for i in range(model_iter):
        print("----------------------------------------")
        print("NETWORK MODEL")
        print("path: ", structural_emb_path)
        # --------------------------------------------------------
        # ------------------NETWORK CONSTRUCTION------------------
        # --------------------------------------------------------

        # read from file and re-establish a copy of the original network
        full_G = nx.read_gml(original_G_path)
        print('# of full network edges ', len(full_G.edges()))
        print('# of full network nodes ', len(full_G.nodes()))

        print("In establishing training network")

        training_G_path, num_of_test_edges = establish_training_G(full_G, re_build_g)

        print("Training network completed")

        # load the training network directly from file
        print("In loading training network")
        # read the training_G from file and obtain a dict of {node: node_emb}
        training_G, structural_emb_dict = load_graph(training_G_path, structural_emb_path=structural_emb_path)

        # load content embedding information from that file
        content_emb_dict = pickle.load(open(content_emb_path, 'rb'))

        print("Training network loaded")

        # get the training_X and labels y
        print('In loading training network')

        full_G = nx.read_gml(original_G_path)

        X_train, y_train, X_test_negatives, y_test_negatives, all_selected_indices, index2pair_dict \
            = load_training_data(full_G, training_G, structural_emb_dict, content_emb_dict,
                                 num_of_test_edges)

        print("shape of X_train: ", X_train.shape)
        print("shape of y_train: ", y_train.shape)

        print('In loading test network')
        # test set is the set difference between edges in the original network and the new network
        full_G = nx.read_gml(original_G_path)
        # fill in the test set
        X_test, y_test = load_test_data(full_G,
                                        list(set(full_G.edges()) - set(training_G.edges())),
                                        structural_emb_dict, content_emb_dict,
                                        X_test_negatives, y_test_negatives)
        print("shape of X_test: ", X_test.shape)
        print("shape of y_test: ", y_test.shape)

        # --------------------------------------------------------
        # ------------------MODEL TRAINING -----------------------
        # --------------------------------------------------------

        print("----------------------------------------")
        print("PREDICTION MODEL")
        if not pred:
            print('Training...')
            # get the prediction accuracy on training set
            # for model in classification_models:
            classifier_instance = Classifier(X_train, y_train, X_test, y_test, classifier)
            classifier_instance.train()
            accuracy, report, macro_roc_auc_ovo, weighted_roc_auc_ovo = classifier_instance.test_model()
            return accuracy, report, macro_roc_auc_ovo, weighted_roc_auc_ovo
        else:
            print('Predicting...')
            full_X_train = np.vstack([X_train, X_test])
            full_y_train = np.concatenate([y_train.flatten(), y_test])
            new_classifier_instance = Classifier(full_X_train, full_y_train, None, None, classifier)
            new_classifier_instance.train()
            if i == model_iter - 1:
                new_classifier_instance.predict(full_G=full_G, all_selected_indices=all_selected_indices,
                                                index2pair_dict=index2pair_dict, binding=binding, infection=infection,
                                                last_iter=True)
            else:
                new_classifier_instance.predict(full_G=full_G, all_selected_indices=all_selected_indices,
                                                index2pair_dict=index2pair_dict, binding=binding, infection=infection,
                                                last_iter=False)


def process_comparison(original_G_path, structural_emb_path, classifier, re_build_g):
    # --------------------------------------------------------
    # --------------------Link prediction---------------------
    # --------------------------------------------------------
    print("----------------------------------------")
    print("MODEL CONSTRUCTION")
    # read from file and re-establish a copy of the original network
    full_G = nx.read_gml(original_G_path)
    print('original num of edges: ', len(full_G.edges()))

    print("In establishing training network")
    training_G_path, num_of_test_edges = establish_training_G(full_G, re_build_g)

    # load the training network directly from file
    print("In loading training network")
    # read the training_G from file and obtain a dict of {node: node_emb}
    training_G, structural_emb_dict = load_graph(training_G_path,
                                                 structural_emb_path=structural_emb_path)
    print("Training network loaded")

    # get the training_X and labels y
    print('In loading training classifier')

    full_G = nx.read_gml(original_G_path)

    X_train, y_train, X_test_to_add, y_test_to_add, all_selected_indices, index2pair_dict \
        = load_training_data(full_G, training_G, structural_emb_dict, None,
                             num_of_test_edges)

    print("shape of X_train: ", X_train.shape)
    print("shape of y_train: ", y_train.shape)

    print('In loading test classifier')
    # test set is the set difference between edges in the original network and the new network
    full_G = nx.read_gml(original_G_path)
    # fill in the test set
    X_test, y_test = load_test_data(full_G,
                                    list(set(full_G.edges()) - set(training_G.edges())),
                                    structural_emb_dict, None,
                                    X_test_to_add, y_test_to_add)

    print("shape of X_test: ", X_test.shape)
    print("shape of y_test: ", y_test.shape)

    print('In testing classification model')

    classifier_instance = Classifier(X_train, y_train, X_test, y_test, classifier)
    classifier_instance.train()
    accuracy, report, macro_roc_auc_ovo, weighted_roc_auc_ovo = classifier_instance.test_model()

    return accuracy, report, macro_roc_auc_ovo, weighted_roc_auc_ovo


def comp_helper(original_G_path, structural_emb_path, content_emb_path, classifier, model_iter):
    print("In performing comparison")
    perf = {}
    for i in range(model_iter):
        for emb in range(len(structural_emb_path)):
            emb_name = str(structural_emb_path[emb]).rsplit('/', 1)[1].split('.')[0]
            if 'CrossNELP' in str(structural_emb_path[emb]):
                print('\nTesting our model CrossNELP')
                if emb == 0:
                    acc, report, macro_roc_auc_ovo, weighted_roc_auc_ovo = \
                        process(original_G_path=original_G_path,
                                structural_emb_path=structural_emb_path[emb],
                                content_emb_path=content_emb_path,
                                classifier=classifier,
                                pred=False,
                                model_iter=1,
                                re_build_g=True)
                else:
                    acc, report, macro_roc_auc_ovo, weighted_roc_auc_ovo = \
                        process(original_G_path=original_G_path,
                                structural_emb_path=structural_emb_path[emb],
                                content_emb_path=content_emb_path,
                                classifier=classifier,
                                pred=False,
                                model_iter=1,
                                re_build_g=False)

            else:
                print('\nTesting comparison model ', emb_name)
                if emb == 0:
                    acc, report, macro_roc_auc_ovo, weighted_roc_auc_ovo = \
                        process_comparison(original_G_path=original_G_path,
                                           structural_emb_path=structural_emb_path[emb],
                                           classifier='MLP',
                                           re_build_g=True)
                else:
                    acc, report, macro_roc_auc_ovo, weighted_roc_auc_ovo = \
                        process_comparison(original_G_path=original_G_path,
                                           structural_emb_path=structural_emb_path[emb],
                                           classifier='MLP',
                                           re_build_g=False)
            if i == 0:
                perf[emb_name] = {}
                perf[emb_name]['PPI_f1'] = []
                perf[emb_name]['PPI_precision'] = []
                perf[emb_name]['PPI_recall'] = []
                perf[emb_name]['ROC_score_macro'] = []
                perf[emb_name]['ROC_score_weighted'] = []
                perf[emb_name]['accuracy'] = []
                perf[emb_name]['infection_f1'] = []
                perf[emb_name]['infection_precision'] = []
                perf[emb_name]['infection_recall'] = []
                perf[emb_name]['weighted_f1'] = []
                perf[emb_name]['weighted_precision'] = []
                perf[emb_name]['weighted_recall'] = []
            append_res(perf[emb_name]['PPI_f1'], perf[emb_name]['PPI_precision'], perf[emb_name]['PPI_recall'],
                       perf[emb_name]['ROC_score_macro'], perf[emb_name]['ROC_score_weighted'],
                       acc,
                       perf[emb_name]['accuracy'], perf[emb_name]['infection_f1'],
                       perf[emb_name]['infection_precision'],
                       perf[emb_name]['infection_recall'],
                       macro_roc_auc_ovo, report,
                       perf[emb_name]['weighted_f1'], perf[emb_name]['weighted_precision'],
                       perf[emb_name]['weighted_recall'],
                       weighted_roc_auc_ovo)

    # write overall performance
    with open(os.path.abspath('data/evaluation/comparison.csv'), 'w') as file:
        file.write(
            'embedding model,infection precision,infection recall,infection f1-score,PPI precision,PPI recall,'
            'PPI f1-score,accuracy,weighted precision,weighted recall,weighted f1-score,ROC macro,ROC weighted\n'
        )
        for emb in range(len(structural_emb_path)):
            emb_name = str(structural_emb_path[emb]).rsplit('/', 1)[1].split('.')[0]
            # write model performance to file after multiple iterations are complete
            to_write = write_res(emb_name,
                                 perf[emb_name]['PPI_f1'],
                                 perf[emb_name]['PPI_precision'],
                                 perf[emb_name]['PPI_recall'],
                                 perf[emb_name]['ROC_score_macro'],
                                 perf[emb_name]['ROC_score_weighted'],
                                 perf[emb_name]['accuracy'],
                                 perf[emb_name]['infection_f1'],
                                 perf[emb_name]['infection_precision'],
                                 perf[emb_name]['infection_recall'],
                                 perf[emb_name]['weighted_f1'],
                                 perf[emb_name]['weighted_precision'],
                                 perf[emb_name]['weighted_recall'])
            file.write(to_write)

    # write performance details
    with open(os.path.abspath('data/evaluation/comparison_details.csv'), 'w') as file:
        file.write(
            'embedding model,infection precision,infection recall,infection f1-score,PPI precision,PPI recall,'
            'PPI f1-score,accuracy,weighted precision,weighted recall,weighted f1-score,ROC macro,ROC weighted\n'
        )
        for emb in range(len(structural_emb_path)):
            emb_name = str(structural_emb_path[emb]).rsplit('/', 1)[1].split('.')[0]
            # write model performance to file after multiple iterations are complete
            to_write = write_res_details(emb_name,
                                         perf[emb_name]['PPI_f1'],
                                         perf[emb_name]['PPI_precision'],
                                         perf[emb_name]['PPI_recall'],
                                         perf[emb_name]['ROC_score_macro'],
                                         perf[emb_name]['ROC_score_weighted'],
                                         perf[emb_name]['accuracy'],
                                         perf[emb_name]['infection_f1'],
                                         perf[emb_name]['infection_precision'],
                                         perf[emb_name]['infection_recall'],
                                         perf[emb_name]['weighted_f1'],
                                         perf[emb_name]['weighted_precision'],
                                         perf[emb_name]['weighted_recall'])
            file.write(to_write)


def write_res(emb_name, PPI_f1, PPI_precision, PPI_recall, ROC_score_macro, ROC_score_weighted, accuracy, infection_f1,
              infection_precision, infection_recall, weighted_f1, weighted_precision, weighted_recall):
    to_write = emb_name + ',' + str(
        np.mean(infection_precision)) + ' ± ' + str(np.std(infection_precision)) + ',' + str(
        np.mean(infection_recall)) + ' ± ' + str(np.std(infection_recall)) + ',' + str(
        np.mean(infection_f1)) + ' ± ' + str(np.std(infection_f1)) + ',' + str(
        np.mean(PPI_precision)) + ' ± ' + str(np.std(PPI_precision)) + ',' + str(
        np.mean(PPI_recall)) + ' ± ' + str(np.std(PPI_recall)) + ',' + str(
        np.mean(PPI_f1)) + ' ± ' + str(np.std(PPI_f1)) + ',' + str(
        np.mean(accuracy)) + ' ± ' + str(np.std(accuracy)) + ',' + str(
        np.mean(weighted_precision)) + ' ± ' + str(np.std(weighted_precision)) + ',' + str(
        np.mean(weighted_recall)) + ' ± ' + str(np.std(weighted_recall)) + ',' + str(
        np.mean(weighted_f1)) + ' ± ' + str(np.std(weighted_f1)) + ',' + str(
        np.mean(ROC_score_macro)) + ' ± ' + str(np.std(ROC_score_macro)) + ',' + str(
        np.mean(ROC_score_weighted)) + ' ± ' + str(np.std(ROC_score_weighted)) + '\n'
    return to_write


def write_res_details(emb_name, PPI_f1, PPI_precision, PPI_recall, ROC_score_macro, ROC_score_weighted, accuracy,
                      infection_f1,
                      infection_precision, infection_recall, weighted_f1, weighted_precision, weighted_recall):
    to_write = ''
    for i in range(len(PPI_f1)):
        to_write = to_write + emb_name + ',' + str(
            infection_precision[i]) + ',' + str(
            infection_recall[i]) + ',' + str(
            infection_f1[i]) + ',' + str(
            PPI_precision[i]) + ',' + str(
            PPI_recall[i]) + ',' + str(
            PPI_f1[i]) + ',' + str(
            accuracy[i]) + ',' + str(
            weighted_precision[i]) + ',' + str(
            weighted_recall[i]) + ',' + str(
            weighted_f1[i]) + ',' + str(
            ROC_score_macro[i]) + ',' + str(
            ROC_score_weighted[i]) + ',' + '\n'

    return to_write


def append_res(PPI_f1, PPI_precision, PPI_recall, ROC_score_macro, ROC_score_weighted, acc, accuracy, infection_f1,
               infection_precision, infection_recall, macro_roc_auc_ovo, report, weighted_f1, weighted_precision,
               weighted_recall, weighted_roc_auc_ovo):
    infection_precision.append(report['2.0']['precision'])
    PPI_precision.append(report['4.0']['precision'])
    infection_recall.append(report['2.0']['recall'])
    PPI_recall.append(report['4.0']['recall'])
    infection_f1.append(report['2.0']['f1-score'])
    PPI_f1.append(report['4.0']['f1-score'])
    accuracy.append(acc)
    weighted_precision.append(report['weighted avg']['precision'])
    weighted_recall.append(report['weighted avg']['recall'])
    weighted_f1.append(report['weighted avg']['f1-score'])
    ROC_score_macro.append(macro_roc_auc_ovo)
    ROC_score_weighted.append(weighted_roc_auc_ovo)