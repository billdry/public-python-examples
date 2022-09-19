#!/usr/bin/env python3

# copyright 2020 Bill Dry
# Return chosen public AWS resource types per public subnet

# Import AWS modules for python
import botocore
import boto3
import boto3.session

# Importing defaultdict module
from collections import defaultdict

# Import RegEx module
import re


# mySession = boto3.session.Session(region_name="us-east-1")


def getPublicSubnets(region):
    try:
        client = boto3.client("ec2", region_name=region)

        rtblResponse = dict()
        rtblResponse = client.describe_route_tables()

        snetResponse = dict()
        snetResponse = client.describe_subnets()

        vpcSubnets = defaultdict(list)

        for subnet in snetResponse["Subnets"]:
            vpcSubnets[subnet["VpcId"]].append(subnet["SubnetId"])

        candidateSubnets = list()
        publicSubnets = list()

        # Identify public subnets by finding subnet route tables w/ Internet gateways
        for routeTable in rtblResponse["RouteTables"]:
            if routeTable["Associations"][0]["Main"]:
                candidateSubnets = vpcSubnets[routeTable["VpcId"]]

            for association in routeTable["Associations"]:
                if "SubnetId" in association:
                    candidateSubnets.append(association["SubnetId"])

            for route in routeTable["Routes"]:
                if "GatewayId" in route:
                    if re.search("^igw-", route["GatewayId"]):
                        publicSubnets.extend(candidateSubnets)

            candidateSubnets.clear()

    except botocore.exceptions.ClientError as error:
        publicSubnets.clear()
        print("Boto3 API returned error: ", error)

    return publicSubnets


# Identify EC2 instances in public subnets
def getPublicEc2Instances(publicSubnets, region):
    try:
        client = boto3.client("ec2", region_name=region)
        response = client.describe_instances(
            Filters=[
                {
                    "Name": "network-interface.subnet-id",
                    "Values": [",".join(publicSubnets)],
                }
            ]
        )

        publicEc2Instances = list()

        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                publicEc2Instances.append(instance["InstanceId"])

    except botocore.exceptions.ClientError as error:
        publicEc2Instances.clear()
        print("Boto3 API returned error: ", error)

    return publicEc2Instances


# List Elastic Load Balancers in public subnets
def getPublicLoadBalancers(publicSubnets, region):
    pass
    publicLoadBalancers = list()
    try:
        client = boto3.client("elbv2", region_name=region)

        response = client.describe_load_balancers()

        for loadBalancer in response["LoadBalancers"]:
            for availabilityZone in loadBalancer["AvailabilityZones"]:
                if availabilityZone["SubnetId"] in publicSubnets:
                    publicLoadBalancers.append(loadBalancer["LoadBalancerArn"])
                    print(
                        "Load balancer: "
                        + loadBalancer["LoadBalancerArn"]
                        + " is IN public subnet: "
                        + availabilityZone["SubnetId"]
                    )
                else:
                    print(
                        "Load balancer: "
                        + loadBalancer["LoadBalancerArn"]
                        + " is NOT IN a public subnet"
                    )

    except botocore.exceptions.ClientError as error:
        publicLoadBalancers.clear()
        print("Boto3 API returned error: ", error)

    return publicLoadBalancers


# Find all public subnets & public resources across all AWS regions
# mySession = boto3.session.Session()
# availableRegions = mySession.get_available_regions(service_name='ec2', partition_name='aws')
# allPublicSubnets = list()
# allPublicInstances = dict()
# for region in availableRegions:
#    response = getPublicSubnets(region)
#    if response:
#        regionPublicInstances = getPublicEc2Instances(response, region)
#        if regionPublicInstances:
#            print("The public EC2 instances in region {} are: {}".format(region, regionPublicInstances))
# allPublicSubnets.extend(response)
#        regionPublicLbs = getPublicLoadBalancers(response, region)
#        if regionPublicLbs:
#            print("The public load balancers in region {} are: {}".format(region, regionPublicLbs))


def lambda_handler(event, context):
    complianceValue = "NOT_APPLICABLE"
    config = boto3.client("config")
    configEvent = json.loads(event["invokingEvent"])
    region = configEvent["configurationItem"]["awsRegion"]
    regionPublicInstances = list()
    resourceId = configEvent["configurationItem"]["resourceId"]

    response = getPublicSubnets(region)
    if response:
        regionPublicInstances = getPublicEc2Instances(response, region)
        # print("The public EC2 instances in region {} are: {}".format(region, regionPublicInstances))

    if configEvent["configurationItem"]["resourceType"] != "AWS::EC2::Instance":
        complianceValue = "NOT_APPLICABLE"
    elif resourceId in regionPublicInstances:
        complianceValue = "NON_COMPLIANT"
        print(
            "EC2 instance: {} in region: {} is {}".format(
                resourceId, region, complianceValue
            )
        )
    else:
        complianceValue = "COMPLIANT"
        print(
            "EC2 instance: {} in region: {} is {}".format(
                resourceId, region, complianceValue
            )
        )

    response = config.put_evaluations(
        Evaluations=[
            {
                "ComplianceResourceType": configEvent["configurationItem"][
                    "resourceType"
                ],
                "ComplianceResourceId": resourceId,
                "ComplianceType": complianceValue,
                "Annotation": "Is this EC2 instance in a public subnet?",
                "OrderingTimestamp": configEvent["configurationItem"][
                    "configurationItemCaptureTime"
                ],
            },
        ],
        ResultToken=event["resultToken"]
        # TestMode=True)
    )
