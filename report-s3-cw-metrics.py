#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# Author - Bill Dry - bdry@amazon.com

# Purpose - Report AWS CloudWatch metrics --NumberOfObjects & BucketSizeBytes-- for S3 buckets
#           This script reports these metrics for every account profile listed in ~/.aws/credentials

# Import AWS modules for python
import botocore
import boto3

# Import module to log messages to file
import logging

# Import regex checking
import re

# Instantiate logging for using its file name
logging.basicConfig(
    filename="report-s3-cw-metrics.log",
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
    level=logging.INFO,
)  # logLevel options are DEBUG, INFO, WARNING, ERROR or CRITICAL
log = logging.getLogger(__name__)

# Function to return a list of all S3 buckets


def get_s3_buckets(resource_type, region, profile):
    bucket_list = list()
    try:
        this_session = boto3.session.Session(profile_name=profile, region_name=region)
        s3 = this_session.resource(resource_type, region_name=region)
        all_buckets_list = s3.buckets.all()
        s3_client = this_session.client(resource_type, region_name=region)
        # return only buckets in the user-specified region
        for bucket in all_buckets_list:
            try:
                response = s3_client.get_bucket_location(Bucket=bucket.name)
                if region == response.get("LocationConstraint"):
                    bucket_list.append(bucket.name)
                # S3 API returns null if bucket located in us-east-1.   Love to know how much that saves!?!?
                elif not response.get("LocationConstraint") and region == "us-east-1":
                    bucket_list.append(bucket.name)
            except botocore.exceptions.ClientError as error:
                log.error(
                    "Bucket: {} - Boto3 API returned error: {}".format(
                        bucket.name, error
                    )
                )
        return bucket_list
    except botocore.exceptions.ClientError as error:
        log.error("Boto3 API returned error: {}".format(error))
        bucket_list.clear()
        return bucket_list


# Function to get CloudWatch Metrics
# Returns the first metric period datapoint for S3 bucket size (bytes) or number of bucket objects


def get_s3_cw_metrics(
    metric_name,
    bucket_name,
    storage_type,
    start_time,
    end_time,
    resource_type,
    region,
    profile,
):
    try:
        this_session = boto3.session.Session(profile_name=profile, region_name=region)
        s3_cw_metric = this_session.client(resource_type, region_name=region)
        response = s3_cw_metric.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName=metric_name,
            Dimensions=[
                {"Name": "BucketName", "Value": bucket_name},
                {"Name": "StorageType", "Value": storage_type},
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,  # S3 period is always one day (86400 seconds)
            Statistics=["Average"],
        )
        # For quick indication, just return the first datapoint in the specified time period
        if response["Datapoints"]:
            return response["Datapoints"][0]["Average"]
        else:
            return False
    except botocore.exceptions.ClientError as error:
        log.error("Boto3 API returned error: {}".format(error))
        return False


# Get a list of all AWS account profiles from ~/.aws/credentials & AWS service regions
mySession = boto3.session.Session(region_name="us-east-1")
availableProfiles = mySession.available_profiles
availableRegions = mySession.get_available_regions(
    service_name="cloudwatch", partition_name="aws"
)

# Get user input
region_name = input("Please enter the AWS region name: ")
if not region_name or region_name not in availableRegions:
    region_name = "us-east-1"
print("You entered: {}".format(region_name))
start_time = input("Please enter the start date in YYYY-MM-DD format: ")
if not start_time or re.search("^[1-2][0-9]{3}-[0-1][0-9]-[0-3][0-9]$", start_time):
    start_time = "2020-10-01"
print("You entered: {}".format(start_time))
start_time += "T00:00:00Z"
end_time = input("Please enter the end date in YYYY-MM-DD format: ")
if not end_time or re.search("^[1-2][0-9]{3}-[0-1][0-9]-[0-3][0-9]$", end_time):
    end_time = "2020-10-02"
print("You entered: {}".format(end_time))
end_time += "T23:59:59Z"
print("\n")

# Execution logic to return the buckets & their sizes per account profile
for profile in availableProfiles:
    print("\nFor AWS Profile: ", profile)
    bucket_list = list()
    bucket_list = get_s3_buckets("s3", region_name, profile)

    if bucket_list:
        for bucket in bucket_list:
            number = get_s3_cw_metrics(
                "NumberOfObjects",
                bucket,
                "AllStorageTypes",
                start_time,
                end_time,
                "cloudwatch",
                region_name,
                profile,
            )
            if number:
                size = get_s3_cw_metrics(
                    "BucketSizeBytes",
                    bucket,
                    "StandardStorage",
                    start_time,
                    end_time,
                    "cloudwatch",
                    region_name,
                    profile,
                )
                print(
                    "Bucket: {} has total size: {:.0f} bytes & contains {:.0f} objects.".format(
                        bucket, size, number
                    )
                )
            else:
                print(
                    "Bucket: {} contains no objects during specified date range.".format(
                        bucket
                    )
                )
    else:
        print("No buckets found")
