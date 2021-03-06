#from helpers import *
#from models import *
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.metrics import average_precision_score
from sklearn.model_selection import KFold, StratifiedKFold
from keras.layers import Dense, Dropout, Input, BatchNormalization
from keras.models import Model
from keras.layers.convolutional import *
import keras.backend as K
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV
from keras import regularizers
from keras.layers import merge
from keras.optimizers import Adam
import pandas as pd

data_dir = '/mnt/raid1/TB_data/tb_data_050818/'
valid_data_dir = '/mnt/raid1/TB_data/validation_data_052318/'

# Create genotype table
X_with_names_df = pd.read_csv(valid_data_dir + 'X_features_with_names.csv', index_col=0)
valid_geno_df = pd.read_table(valid_data_dir + 'genotype_NNvalid_corr.tsv')
valid_geno_df['status'] = 1
table = valid_geno_df.pivot_table(index='strainname', columns='snpname', values='status').fillna(0)

# Get drug phenotypes for 11 drugs we are testing
valid_pheno_df = pd.read_table(valid_data_dir + 'phenotype_NNvalid.tsv')
cols = ['name', 'RIF', 'INH', 'PZA', 'EMB', 'STR', 'CIP', 'CAP', 'AMK', 'MOXI', 'OFLX', 'KAN']
valid_pheno_df = valid_pheno_df[cols]

# Merge genotype and phenotype data
table['name'] = table.index
merged_validation_data = pd.merge(table, valid_pheno_df, on='name', how="outer").fillna("")
merged_validation_data.drop('name', axis=1, inplace=True)

# Get rare mutations for which we will make derived class
features_inds = np.array(merged_validation_data.columns[:1181])
df_X_val = merged_validation_data[features_inds]
derived_snp_inds = np.squeeze(np.where(df_X_val.sum(axis=0) < 30))
derived_names_rare = list(df_X_val[features_inds].columns.values[derived_snp_inds])

# Get proper y labels
y_true_val_inds = merged_validation_data.columns[1181:]
categories = {'R':0, 'S':1, 'I':0, '':-1}
y_true_val = merged_validation_data[y_true_val_inds].replace(categories)

# Get dictionary by gene
gene_dict = get_gene_dict(derived_names_rare)

# Get dictionary by gene and mutation type
final_dict = get_final_dict(gene_dict)

# Add to features
for gene in final_dict.keys():
    if not gene in X_with_names_df.columns:
        continue
    new_col = df_X_val[final_dict[gene]].sum(axis=1)
    new_col[new_col != 0] = 1
    df_X_val[gene] = pd.Series(new_col, index=df_X_val.index)

# Find SNPs in validation and training data sets
validation_gene_names = np.array(df_X_val.columns.tolist())
valid_snp_inds_all = np.squeeze(np.where((X_with_names_df == 1).sum(axis=0) >= 30))
gene_names = np.array(X_with_names_df.columns[valid_snp_inds_all].tolist())
intersect_genes = np.intersect1d(validation_gene_names, gene_names)

# Data frame for all SNPs found in validation set and training set
small_df_X_val = df_X_val[intersect_genes]

# Create properly sized features data frame, filling in zeros for mutations found in no validation isolates
full_validation_df = pd.DataFrame(0, columns=X_with_names_df.columns[valid_snp_inds_all], index=np.arange(792))
full_validation_df[small_df_X_val.columns] = small_df_X_val

df_X = X_with_names_df[X_with_names_df.columns[valid_snp_inds_all]]

# Save validation data and true validation labels as CSV
full_validation_df.to_csv("validation_data.csv", index=False)
y_true_val.to_csv("validation_data_pheno.csv", index=False)

#X_test_df = pd.read_csv(data_dir + "validation_data.csv")
#y_test_df = pd.read_csv(data_dir + "validation_data_pheno.csv")

# Get training data and independent test set to numpy arrays
X_test = full_validation_df.as_matrix()
y_test = y_true_val.as_matrix()

X = df_X.as_matrix()
alpha_matrix = np.loadtxt(data_dir + 'alpha_matrix.csv', delimiter=',')
y = np.loadtxt(data_dir + 'labels.csv', delimiter=',')

# Mutations unavailable through subset of isolates that underwent targeted sequencing
X[X == -1] = 0.5

# Drugs
num_drugs = 11
drugs = ['rif', 'inh', 'pza', 'emb', 'str', 'cip', 'cap', 'amk', 'moxi', 'oflx', 'kan']

# Run multitask WDNN
wdnn = get_wide_deep()
wdnn.fit(X, alpha_matrix, epochs=100)
wdnn_probs = wdnn.predict(X_test)

with open('/mnt/raid1/TB_data/test_probs.csv', 'a') as f:
    df = pd.DataFrame(wdnn_probs)
    df.to_csv(f, header=False, index=False)

with open('/mnt/raid1/TB_data/test_labels.csv', 'a') as f:
    df = pd.DataFrame(y_test)
    df.to_csv(f, header=False, index=False)

# Get AUC data for WDNN
column_names = ['Algorithm','Drug','AUC']
results = pd.DataFrame(columns=column_names)
results_index = 0

for i, drug in enumerate(drugs):
    if drug != 'cip':
        non_missing_val = np.where(y_test[:, i] != -1)[0]
        ## Flip it so resistance is the positive class
        auc_y = np.abs(np.reshape(1-np.abs(y_test[non_missing_val, i]), (len(non_missing_val), 1)))
        auc_preds = np.reshape(1-wdnn_probs[non_missing_val, i], (len(non_missing_val), 1))
        val_auc = roc_auc_score(auc_y, auc_preds)
        results.loc[results_index] = ['WDNN', drug, val_auc]
        print (drug + "\t" + str(val_auc))
        results_index += 1

################## Get Precision-Recall Results ########################
wdnn_probs = pd.read_csv("preds/test_probs_WDNN.csv", header=None).values
lr_probs = pd.read_csv("preds/test_probs_lr_111918.csv", header=None).values

# Get Precision-Recall data for WDNN
column_names = ['Algorithm','Drug','PR']
results = pd.DataFrame(columns=column_names)
results_index = 0

for i, drug in enumerate(drugs):
    if drug != 'cip':
        non_missing_val = np.where(y_test[:, i] != -1)[0]
        ## Flip it so resistance is the positive class
        pr_y = np.abs(np.reshape(1-np.abs(y_test[non_missing_val, i]), (len(non_missing_val), 1)))
        pr_preds = np.reshape(1-wdnn_probs[non_missing_val, i], (len(non_missing_val), 1))
        val_pr = average_precision_score(pr_y, pr_preds)
        results.loc[results_index] = ['WDNN', drug, val_pr]
        print (drug + "\t" + str(val_pr))
        results_index += 1

# Get Precision-Recall data for LR
for i, drug in enumerate(drugs):
    if drug != 'cip':
        non_missing_val = np.where(y_test[:, i] != -1)[0]
        ## Flip it so resistance is the positive class
        pr_y = np.abs(np.reshape(1-np.abs(y_test[non_missing_val, i]), (len(non_missing_val), 1)))
        pr_preds = np.reshape(1-lr_probs[non_missing_val, i], (len(non_missing_val), 1))
        val_pr = average_precision_score(pr_y, pr_preds)
        results.loc[results_index] = ['Logistic Regression', drug, val_pr]
        print (drug + "\t" + str(val_pr))
        results_index += 1

results.to_csv('results_020719/validation_pr_020719.csv',index=False)
########################################################################

# Get performance data for RF and LR
for i, drug in enumerate(drugs):
    if drug != 'cip':
        y_drug = y[:, i]
        # Disregard rows for which no resistance data exists
        y_non_missing = y_drug[y_drug != -1]
        X_non_missing = X[y_drug != -1]
        X_train = X_non_missing
        y_train = y_non_missing
        # Train and predict on random forest classifier
        random_forest = RandomForestClassifier(n_estimators=1000, max_features='auto', min_samples_leaf=0.002)
        random_forest.fit(X_train, y_train)
        # Get AUC of drug for RF
        y_test_non_missing = y_test[y_test[:,i] != -1,i]
        X_test_non_missing = X_test[y_test[:, i] != -1, :]
        pred_rf = random_forest.predict_proba(X_test_non_missing)
        rf_auc = roc_auc_score(y_test_non_missing, pred_rf[:, 1])
        results.loc[results_index] = ['Random Forest', drug, rf_auc]
        results_index += 1
        # Train and predict on regularized logistic regression model
        log_reg = LogisticRegression(penalty='l2', solver="liblinear")
        Cs = np.logspace(-5, 5, 10)
        estimator = GridSearchCV(estimator=log_reg, param_grid={'C': Cs}, cv=5, scoring='roc_auc')
        estimator.fit(X_train, y_train)
        pred_lm = estimator.predict_proba(X_test_non_missing)
        full_pred_lm = estimator.predict_proba(X_test)
        if i == 0:
            test_probs_lm = np.array(full_pred_lm[:,1])
        else:
            test_probs_lm = np.column_stack((test_probs_lm,full_pred_lm[:,1]))
        lm_auc = roc_auc_score(y_test_non_missing, pred_lm[:, 1])
        results.loc[results_index] = ['Logistic Regression', drug, lm_auc]
        results_index += 1
    else:
        test_probs_lm = np.column_stack((test_probs_lm, -np.ones_like(y_test[:,i])))

with open('raw_results_111918/test_probs_lr_111918.csv', 'a') as f:
    df = pd.DataFrame(test_probs_lm)
    df.to_csv(f, header=False, index=False)

with open('raw_results_111918/test_probs_lrwdnn_ensemble_122218.csv', 'a') as f:
    df = pd.DataFrame((test_probs_lm+wdnn_probs)/2)
    df.to_csv(f, header=False, index=False)

# Get performance data for single task WDNN
for i, drug in enumerate(drugs):
    if drug == "cip":
        continue
    # Label data for current drug
    y_true_drug = y[:,i]
    # Disregard rows for which no resistance data exists
    y_true_small = y_true_drug[y_true_drug != -1]
    X_small = X[y_true_drug != -1]
    # Get test data for current drug and proper SNPs
    y_test_drug = y_test[:,i]
    y_test_small = y_test_drug[y_test_drug != -1]
    X_test_small = X_test[y_test_drug != -1]
    # Train on MLP
    wdnn_single = get_wide_deep_single()
    wdnn_single.fit(X_small, y_true_small, epochs=100)
    #clf_dos = K.Function(clf_s.inputs + [K.learning_phase()], clf_s.outputs)
    #wdnn_single_preds = ensemble(X_val, np.expand_dims(y_val, axis=1), wdnn_single_mc_dropout)
    wdnn_single_preds = wdnn_single.predict(X_test_small)
    # Get AUC, specificity, and sensitivity of drug for single task WDNN
    wdnn_single_auc = roc_auc_score(y_test_small.reshape(len(y_test_small), 1),
                                    wdnn_single_preds.reshape((len(wdnn_single_preds), 1)))
    results.loc[results_index] = ['WDNN Single Task', drug, wdnn_single_auc]
    results_index += 1


results.to_csv('/mnt/raid1/TB_data/results_validation.csv',index=False)


# Load pre-selected SNPs
rif_snps = np.loadtxt("rif_snps.csv", delimiter=",", dtype=np.dtype('S'))
inh_snps = np.loadtxt("inh_snps.csv", delimiter=",", dtype=np.dtype('S'))
pza_snps = np.loadtxt("pza_snps.csv", delimiter=",", dtype=np.dtype('S'))
emb_snps = np.loadtxt("emb_snps.csv", delimiter=",", dtype=np.dtype('S'))
str_snps = np.loadtxt("str_snps.csv", delimiter=",", dtype=np.dtype('S'))
cap_snps = np.loadtxt("cap_snps.csv", delimiter=",", dtype=np.dtype('S'))
amk_snps = np.loadtxt("amk_snps.csv", delimiter=",", dtype=np.dtype('S'))
moxi_snps = np.loadtxt("moxi_snps.csv", delimiter=",", dtype=np.dtype('S'))
oflx_snps = np.loadtxt("oflx_snps.csv", delimiter=",", dtype=np.dtype('S'))
kan_snps = np.loadtxt("kan_snps.csv", delimiter=",", dtype=np.dtype('S'))

# List of list of preselected SNPs
num_snp_indiv_val = [rif_snps, inh_snps, pza_snps, emb_snps, str_snps,
                  cap_snps, amk_snps, moxi_snps, oflx_snps, kan_snps]

# Get performance data for preselected SNPs MLP
i = 0
for j, drug in enumerate(drugs):
    # Single task MLP
    def get_mlp_single():
        input = Input(shape=(len(num_snp_indiv_val[i]),))
        x = Dense(512, activation='relu')(input)
        x = Dropout(0.5)(x)
        x = Dense(512, activation='relu')(x)
        x = Dropout(0.5)(x)
        x = Dense(512, activation='relu')(x)
        x = Dropout(0.5)(x)
        preds = Dense(1, activation='sigmoid')(x)
        model = Model(input=input, output=preds)
        model.compile(optimizer='Adam',
                      loss=masked_single_bce,
                      metrics=[masked_accuracy])
        return model
    if drug == "cip":
        continue
    # Get feature and label data for current drug
    X_mlp = df_X[num_snp_indiv_val[i]].as_matrix()
    # Label data for current drug
    y_true_drug = y_true[:,j]
    # Disregard rows for which no resistance data exists
    y_true_small = y_true_drug[y_true_drug != -1]
    X_small = X_mlp[y_true_drug != -1]
    # Get test data for current drug and proper SNPs
    y_test_drug = y_test[:,j]
    y_test_small = y_test_drug[y_test_drug != -1]
    X_test_small = full_validation_df[num_snp_indiv_val[i]].as_matrix()
    X_test_small = X_test_small[y_test_drug != -1]
    # Train on MLP
    clf1 = get_mlp_single()
    clf1.fit(X_small, y_true_small, nb_epoch=50)
    clf_do = K.Function(clf1.inputs + [K.learning_phase()], clf1.outputs)
    y_pred_strat_test = ensemble(X_test_small, np.expand_dims(y_test_small, axis=1), clf_do)
    y_pred_strat_train = ensemble(X_small, np.expand_dims(y_true_small, axis=1), clf_do)
    # Compute AUC scores for validation set
    auc_strat_data_test[i] = roc_auc_score(y_test_small, y_pred_strat_test)
    # Get sensitivity and specificity for validation set
    strat_data_indiv = get_threshold(y_true_small, y_pred_strat_train,
                                     y_test_small, y_pred_strat_test)
    strat_data_indiv = get_sens_spec_from_threshold(y_test_small, y_pred_strat_test,
                                                    strat_thresh_from_cv[j])
    spec_strat_data_test[i] = strat_data_indiv['spec']
    sens_strat_data_test[i] = strat_data_indiv['sens']
    plot_fpr_tpr = plot_roc_auc(drug, y_test_small, y_pred_strat_test)
    fpr_list[:, i + 40] = plot_fpr_tpr['fpr_list']
    tpr_list[:, i + 40] = plot_fpr_tpr['tpr_list']
    i += 1

# List of drugs without CIP for convenience of labeling
drugs_no_cip = ['rif', 'inh', 'pza', 'emb', 'str', 'cap', 'amk', 'moxi', 'oflx', 'kan']

# Plot the ROC curves for the validation data results for each drug
final_plot_roc_auc(drugs_no_cip, fpr_list, tpr_list)

fpr_dom = fpr_list[:,0:10].mean(axis=1)
tpr_dom = tpr_list[:,0:10].mean(axis=1)
fpr_rf = fpr_list[:,10:20].mean(axis=1)
tpr_rf = tpr_list[:,10:20].mean(axis=1)
fpr_lm = fpr_list[:,20:30].mean(axis=1)
tpr_lm = tpr_list[:,20:30].mean(axis=1)
fpr_dos = fpr_list[:,30:40].mean(axis=1)
tpr_dos = tpr_list[:,30:40].mean(axis=1)
fpr_strat = fpr_list[:,40:50].mean(axis=1)
tpr_strat = tpr_list[:,40:50].mean(axis=1)

# Function to plot the average ROC curve for the validation data across all drugs
def plot_average_roc():
    fig = plt.figure()
    plt.plot(fpr_dom, tpr_dom, label='Multi WDNN')
    plt.plot(fpr_rf, tpr_rf, label='RF')
    plt.plot(fpr_lm, tpr_lm, label='LR')
    plt.plot(fpr_dos, tpr_dos, label='Single WDNN')
    plt.plot(fpr_strat, tpr_strat, label='Preselected MLP')
    plt.legend(loc='lower right')
    plt.plot([0, 1], [0, 1], 'black')
    plt.xlim([-.02, 1.02])
    plt.ylim([-.02, 1.02])
    plt.ylabel('True Positive Rate')
    plt.xlabel('False Positive Rate')
    fig.savefig('average_roc.png')

# Actual plot
plot_average_roc()

# Scale sensitivity and specificity to percent
sens_dom_data_test *= 100
sens_rf_data_test *= 100
sens_lm_data_test *= 100
spec_dom_data_test *= 100
spec_rf_data_test *= 100
spec_lm_data_test *= 100
sens_strat_data_test *= 100
spec_strat_data_test *= 100
sens_dos_data_test *= 100
spec_dos_data_test *= 100

# Save predictive performance data
outarr = np.stack((drugs_no_cip, auc_dom_data_test, auc_rf_data_test, auc_lm_data_test,
          spec_dom_data_test, spec_rf_data_test, spec_lm_data_test,
          sens_dom_data_test, sens_rf_data_test, sens_lm_data_test)).T

np.savetxt('auc_spec_sens_val_data_050218.csv', outarr, fmt='%s', delimiter=',',
           header='drugs, auc_dom_data_test, auc_rf_data_test, auc_lm_data_test,'
                    'spec_dom_data_test, spec_rf_data_test, spec_lm_data_test,'
                    'sens_dom_data_test, sens_rf_data_test, sens_lm_data_test')

# Save results
outarr = np.stack((drugs_no_cip, auc_strat_data_test, spec_strat_data_test, sens_strat_data_test)).T

np.savetxt('restricted_snp_val_data_050218.csv', outarr, fmt='%s', delimiter=',',
           header='drugs, auc_strat_data_test, spec_strat_data_test, sens_strat_data_test')

outarr = np.stack((drugs_no_cip, auc_dos_data_test, spec_dos_data_test, sens_dos_data_test)).T

np.savetxt('single_task_wdnn_val_data_050218.csv', outarr, fmt='%s', delimiter=',',
           header='drugs, auc_dos_data_test, spec_dos_data_test, sens_dos_data_test')
