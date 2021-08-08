"""AWS Lambda resource tagger for Amazon EC2 instances.

   Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
   SPDX-License-Identifier: MIT-0

   This AWS Lambda extracts tags from IAM role, IAM user & SSM parameters.
   These extracted tags are applied to Amazon EC2 instances & attached
   EBS volumes.
"""

# Import AWS modules for python
import botocore
import boto3

# Import JSON to post resource tagging results
# to CloudWatch logs as a JSON object
import json


def get_iam_role_tags(role_name):
    """Get resource tags assigned to a specified IAM role.

    Args:
        role_name: IAM role name of entity creating the EC2 instance.

    Returns:
        Returns a list of key:string,value:string resource tag dictionaries
        assigned to the role or an empty list if no tags assigned to the role.

    Raises:
        AWS Python API "Boto3" returned errors
    """
    no_tags = list()
    client = boto3.client("iam")
    try:
        response = client.list_role_tags(RoleName=role_name)
    except botocore.exceptions.ClientError as error:
        print("Boto3 API returned error: ", error)
    if response.get("Tags"):
        return response["Tags"]
    else:
        return no_tags


def get_iam_user_tags(iam_user_name):
    """Get resource tags assigned to a specified IAM user.

    Args:
        iam_user_name: IAM user who created the EC2 instance.

    Returns:
        Returns a list of key:string,value:string resource tag dictionaries
        assigned to the IAM user or an empty list if no tags assigned to the user.

    Raises:
        AWS Python API "Boto3" returned errors
    """
    client = boto3.client("iam")
    no_tags = list()
    try:
        response = client.list_user_tags(UserName=iam_user_name)
    except botocore.exceptions.ClientError as error:
        print("Boto3 API returned error: ", error)
    if response.get("Tags"):
        return response["Tags"]
    else:
        return no_tags


def get_ssm_parameter_tags(**kwargs):
    """Get resource tags stored in AWS SSM Parameter Store.

    Args:
        A key word argument (kwarg) dictionary containing any of:
            iam_user_name: IAM user creating the EC2 instance
            role_name: IAM role name of entity creating the EC2 instance
            user_name: Name of user assuming the IAM role

    Returns:
        Returns a list of key:string,value:string resource tag dictionaries
        Returns an empty list if no resource tags found

    Raises:
        AWS Python API "Boto3" returned errors
    """
    tag_list = list()

    iam_user_name = kwargs.get("iam_user_name", False)
    role_name = kwargs.get("role_name", False)
    user_name = kwargs.get("user_name", False)
    if iam_user_name:
        path_string = "/auto-tag/" + iam_user_name + "/tag"
    elif role_name and user_name:
        path_string = "/auto-tag/" + role_name + "/" + user_name + "/tag"
    else:
        path_string = False
    if path_string:
        ssm_client = boto3.client("ssm")
        try:
            get_parameter_response = ssm_client.get_parameters_by_path(
                Path=path_string, Recursive=True, WithDecryption=True
            )
            for parameter in get_parameter_response.get("Parameters"):
                path_components = parameter["Name"].split("/")
                tag_key = path_components[-1]
                tag_list.append({"Key": tag_key, "Value": parameter.get("Value")})

        except botocore.exceptions.ClientError as error:
            print("Boto3 API returned error: ", error)
            tag_list.clear()
    return tag_list


# Apply resource tags to EC2 instances & attached EBS volumes
def set_ec2_resource_tags(resource_id, resource_tags):
    """Applies a list of passed resource tags to the Amazon EC2 instance.
       Also applies the same resource tags to EBS volumes attached to instance.

    Args:
        resource_id: EC2 instance identifier
        resource_tags: a list of key:string,value:string resource tag dictionaries

    Returns:
        Returns True if tag application successful and False if not

    Raises:
        AWS Python API "Boto3" returned errors
    """
    client = boto3.client("ec2")
    try:
        response = client.create_tags(Resources=[resource_id], Tags=resource_tags)
        response = client.describe_volumes(
            Filters=[{"Name": "attachment.instance-id", "Values": [resource_id]}]
        )
        try:
            for volume in response.get("Volumes"):
                ec2 = boto3.resource("ec2")
                ec2_vol = ec2.Volume(volume["VolumeId"])
                vol_tags = ec2_vol.create_tags(Tags=resource_tags)
        except botocore.exceptions.ClientError as error:
            print("Boto3 API returned error: ", error)
            print("No Tags Applied To: ", response["Volumes"])
            return False
    except botocore.exceptions.ClientError as error:
        print("Boto3 API returned error: ", error)
        print("No Tags Applied To: ", resource_id)
        return False
    return True


def cloudtrail_event_parser(event):
    """Extract list of new EC2 instance attributes, creation date, IAM role name,
    SSO User ID from the AWS CloudTrail resource creation event.

    Args:
        event: a cloudtrail event in JSON format

    Returns:
        iam_user_name: the user name of the IAM user
        instances_set: list of EC2 instances & parameter dictionaries
        resource_date: date the EC2 instance was created
        role_name: IAM role name of entity creating the EC2 instance
        user_name: Name of user assuming the IAM role

    Raises:
        none
    """

    if event.get("detail").get("userIdentity").get("type") == "IAMUser":
        iam_user_name = event.get("detail").get("userIdentity").get("userName", False)

    instances_set = event.get("detail").get("responseElements").get("instancesSet", False)

    resource_date = event.get("detail").get("eventTime", False)

    if (
        event.get("detail").get("userIdentity").get("sessionContext").get("sessionIssuer").get("type")
        == "Role"
    ):
        role_arn = (
            event.get("detail")
            .get("userIdentity")
            .get("sessionContext")
            .get("sessionIssuer")
            .get("arn")
        )
        role_components = role_arn.split("/")
        role_name = role_components[-1]
    else:
        role_name = False

    if event.get("detail").get("userIdentity").get("arn"):
        user_id_arn = event.get("detail").get("userIdentity").get("arn")
        user_id_components = user_id_arn.split("/")
        user_id = user_id_components[-1]
    else:
        user_id = False

    return iam_user_name, instances_set, resource_date, role_name, user_id


def lambda_handler(event, context):
    resource_tags = list()

    (
        iam_user_name,
        instances_set,
        resource_date,
        role_name,
        user_id,
    ) = cloudtrail_event_parser(event)

    if iam_user_name:
        resource_tags.append({"Key": "IAM User Name", "Value": iam_user_name})
        resource_tags += get_iam_user_tags(iam_user_name)
        resource_tags += get_ssm_parameter_tags(iam_user_name=iam_user_name)

    if resource_date:
        resource_tags.append({"Key": "Date created", "Value": resource_date})

    if role_name:
        resource_tags.append({"Key": "IAM Role Name", "Value": role_name})
        resource_tags += get_iam_role_tags(role_name)
        if user_id:
            resource_tags.append({"Key": "Created by", "Value": user_id})
            resource_tags += get_ssm_parameter_tags(role_name=role_name, user_id=user_id)

    if instances_set:
        for item in instances_set.get("items"):
            resource_id = item.get("instanceId")
            if set_ec2_resource_tags(resource_id, resource_tags):
                print(
                    "'statusCode': 200,\n"
                    f"'Resource ID': {resource_id}\n"
                    f"'body': {json.dumps(resource_tags)}"
                )
            else:
                print(
                    "'statusCode': 500,\n"
                    f"'No tags applied to Resource ID': {resource_id},\n"
                    f"'Lambda function name': {context.function_name},\n"
                    f"'Lambda function version': {context.function_version}"
                )
    else:
        print(
            "'statusCode': 200,\n"
            f"'No Amazon EC2 resources to tag': 'Event ID: {event.get('id')}'"
        )
