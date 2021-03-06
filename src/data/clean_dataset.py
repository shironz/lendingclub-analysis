# -*- coding: utf-8 -*-
import click
import logging
from pathlib import Path
from dotenv import find_dotenv, load_dotenv

import pandas as pd

logger = logging.getLogger(__name__)
    
def add_target_variable(df):
    """
    Adds the target variable (1 if loan is defaulted, 0 if not), and removes the loan_status column.

    Parameters:
    df (pandas.DataFrame): Dataframe which contains a "loan_status" column.

    Returns:
    df (pandas.DataFrame): The input dataframe with an added "target" column and with "loan_status" dropped.
    """
    default_client_values = ["Charged Off", "Default", "Does not meet the credit policy. Status:Charged Off", 
                             "Late (31-120 days)"]
    non_default_client_values = ["Fully Paid", "Does not meet the credit policy. Status:Fully Paid"]
    target_values = default_client_values + non_default_client_values
    df["target"] = df["loan_status"].isin(default_client_values)
    return df[df["loan_status"].isin(target_values)].drop(columns=["loan_status"])

def fix_dtypes(df):
    """
    Converts columns to their appropriate types (booleans, dates, categories). 

    Parameters:
    df (pandas.DataFrame): Dataframe of values.

    Returns:
    df (pandas.DataFrame): The input dataframe with type-corrected columns. 
    """
    # Convert columns to boolean flags, and drop the original columns
    df["is_payment_plan"] = df["pymnt_plan"] == "y"
    df["is_whole_loan"] = df["initial_list_status"] == "w"
    df["is_individual_app"] = df["application_type"] == "Individual"
    df["is_36_month_term"] = df["term"] == "36 months"
    df["term_months"] = df["term"].str[1:3].astype(int)
    df["is_cash"] = df["disbursement_method"] == "Cash"
    df.drop(columns = ["pymnt_plan", "initial_list_status", "application_type", 
                       "term", "disbursement_method"], inplace = True)

    # Convert columns to datetime columns
    for col in ["issue_d", "earliest_cr_line"]:
        df[col] = pd.to_datetime(df[col], infer_datetime_format=True)

    # Convert columns to categorical type
    for col in ["grade", "sub_grade", "home_ownership", 
                "verification_status", "purpose", 
                "addr_state"]:
        df[col] = df[col].astype('category')

    # Convert employment length to an integer field.
    # Nb. 10+ years is converted to just 10, < 1 year to 0. 
    df["emp_length"] = df["emp_length"].replace({"10+ years": "10 years", "< 1 year": "0 years"})
    df["emp_length"] = df["emp_length"].str[:2].astype(int)

    # Drop uninformative columns
    df.drop(columns = ["emp_title", "desc", "title", "zip_code"], inplace = True)

    return df

def fix_missing_values(df):
    """
    Deals with missing values in columns.

    Parameters:
    df (pandas.DataFrame): The input dataframe.

    Returns:
    df (pandas.DataFrame): The input dataframe with missing value columns either removed or cleaned. 
    """
    logger.info(f"Columns with missing values before cleaning: {len(df.columns[df.isna().any()])}")

    # These columns have all values missing, so we just drop them. 
    all_values_missing = ["id", "member_id", "url"]
    df.drop(columns = all_values_missing, inplace = True)

    # If employment length is not known, fill with zero. 
    df["emp_length"] = df["emp_length"].fillna("0 years")

    # Use the data dictionary to drop hardship and settlement fields.
    # These columns a) have missing values, b) don't have values set until after the loan is issued. 
    df_data_dictionary = pd.read_excel("references/LCDataDictionary.xlsx").dropna()
    is_settlement_or_hardship = df_data_dictionary["Description"].str.contains("settle|hardship",
                                                                               regex=True, case=False)
    settlement_cols = df_data_dictionary[is_settlement_or_hardship].LoanStatNew.values
    try:
        df.drop(columns = settlement_cols, inplace = True)
    except ValueError:
        df.drop(columns = settlement_cols, inplace = True, errors = 'ignore')

    # Drop all columns and rows relating to joint applications. 
    joint_columns = [x for x in df.columns if ('joint' in x or 'sec_app' in x)]
    df.drop(columns = joint_columns, inplace = True)
    df.drop(df[df["application_type"] != "Individual"].index, inplace = True)

    # Now we work through the remaining columns. 
    columns_remaining = df.columns[df.isna().any()]

    cols_to_drop = []
    cols_to_set_zero = []

    cols_to_drop += ["next_pymnt_d", "last_pymnt_d", "last_pymnt_amnt",
                "last_credit_pull_d"]

    num_cols = [x for x in columns_remaining if x.startswith("num_")]
    cols_to_set_zero += num_cols


    util_cols = [x for x in columns_remaining if "_util" in x]
    cols_to_set_zero += util_cols

    # Drop date columns as uninformative. 
    date_cols = [x for x in columns_remaining if "_d" in x]

    flag_cols = ["max_bal_bc", "open_acc_6m", "open_act_il", "open_il_12m", 
                 "open_il_24m", "total_bal_il", "open_rv_24m", "open_rv_12m", 
                 "inq_last_12m", "inq_fi", "total_cu_tl"]
    cols_to_set_zero += flag_cols

    # Low frequency columns to set to 0
    low_freq_cols = ["tot_cur_bal", "tot_coll_amt", "emp_length", "avg_cur_bal", "tax_liens", "total_rev_hi_lim",
                     "total_il_high_credit_limit", "tot_hi_cred_lim", "pct_tl_nvr_dlq", "percent_bc_gt_75", 
                     "bc_open_to_buy", "mort_acc", "acc_open_past_24mths", "total_bc_limit", "total_bal_ex_mort",
                     "pub_rec_bankruptcies", "collections_12_mths_ex_med", "chargeoff_within_12_mths"]
    cols_to_set_zero += low_freq_cols

    cols_to_drop += ["mths_since_rcnt_il", "mths_since_last_record",
                     "mths_since_recent_bc_dlq", "mths_since_last_major_derog",
                     "mths_since_recent_revol_delinq", "mths_since_last_delinq"]

    # If value is missing here, we assume the event has never happened, so set a boolean flag. 
    df["has_public_record"] = ~df["mths_since_last_record"].isna()
    df["has_recent_bc_dlq"] = ~df["mths_since_recent_bc_dlq"].isna()
    df["has_major_derog"] = ~df["mths_since_last_major_derog"].isna()
    df["has_recent_revol_delinq"] = ~df["mths_since_recent_revol_delinq"].isna()
    df["has_recent_delinq"] = ~df["mths_since_last_delinq"].isna()

    cols_to_set_zero += ["mo_sin_rcnt_rev_tl_op", "mo_sin_rcnt_tl", 
                         "mths_since_recent_inq", "mo_sin_old_rev_tl_op",
                         "mo_sin_old_il_acct",  "mths_since_recent_bc"]
    
    df[cols_to_set_zero] = df[cols_to_set_zero].fillna(0)

    df.drop(columns = cols_to_drop, inplace = True)

    logger.info(f"Columns with missing values after cleaning: {len(df.columns[df.isna().any()])}")
    
    return df

def remove_future_columns(df):
    """
    Removes columns that relate to future events, ie. columns whose values are only set
    after the loan is issued.

    Parameters:
    df (pandas.DataFrame): The input dataframe.

    Returns:
    df (pandas.DataFrame): The input dataframe with future columns dropped. 
    """
    cols = ["collection_recovery_fee", "funded_amnt", "funded_amnt_inv", "out_prncp", "out_prncp_inv",
            "recoveries", "total_pymnt", "total_pymnt_inv", "total_rec_int", "total_rec_late_fee",
            "total_rec_prncp"]
    logger.info(f"Removing {len(cols)} columns")
    df.drop(columns = cols, inplace = True)
    return df

def clean_dataset(df):
    """
    Cleans the dataset by:
    1. Adding the target variable
    2. Dealing with missing values
    3. Fixing types of columns that are incorrectly interpreted

    Parameters:
    df (pandas.DataFrame): The input dataframe
    
    Returns:
    df (pandas.DataFrame): The cleaned input dataframe. 
    """
    # Add target variable
    logger.info("Adding target column")
    df = add_target_variable(df)
    logger.info(f"Target variable counts: \n{df.target.value_counts()}")
    logger.info(f"Dataframe shape after adding target column: {df.shape}")
    
    # Missing values
    logger.info("Fixing missing values")
    df = fix_missing_values(df)
    logger.info(f"Dataframe shape after fixing missing values: {df.shape}")

    # Remove columns that we won't know about when the loan is issued
    df = remove_future_columns(df)
    logger.info(f"Dataframe shape after removing future columns: {df.shape}")    
    # Fix dtypes
    logger.info("Fixing dtypes")
    df = fix_dtypes(df)
    logger.info(f"Dataframe shape after fixing dtypes: {df.shape}")
    
    return df

def clean_dataset_main(input_file, output_file):
    """ 
    Runs data processing scripts to prepare and clean dataset.
    Placing this separately to the main function allows us to call the main function from the command
    line and this function from other Python files. 

    Parameters:
    input_file (string): The location of the input (raw) dataframe. 
    output_file (string): The location to save the intermediate cleaned dataframe. 

    Side effects:
    Saves cleaned dataframe to CSV at output_file location. 
    """
    logger.info('Preparing and cleaning dataset')
    df = pd.read_csv(input_file, low_memory = False)
    logger.info(f"Input dataframe shape: {df.shape}")
    df = clean_dataset(df)
    logger.info(f"Saving cleaned dataframe to {output_file}")
    df.to_csv(output_file, index = False)
    
@click.command()
@click.argument('input_file', type=click.Path(exists=True))
@click.argument('output_file', type=click.Path())
def main(input_file, output_file):
    clean_dataset_main(input_file, output_file)
    
if __name__ == '__main__':
    log_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_fmt)

    # not used in this stub but often useful for finding various files
    project_dir = Path(__file__).resolve().parents[2]

    # find .env automagically by walking up directories until it's found, then
    # load up the .env entries as environment variables
    load_dotenv(find_dotenv())

    main()
