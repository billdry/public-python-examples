#!/usr/bin/env python3

# copyright 2020 Bill Dry
# AWS Lambda function determines if an ELB instance is in a public subnet
# This AWS Config Rule script requires the following 
# IAM permission policy assigned to its Lambda function:
#
# {
#     "Version": "2012-10-17",
#     "Statement": [
#         {
#             "Sid": "VisualEditor0",
#             "Effect": "Allow",
#             "Action": [
#                 "config:PutEvaluations",
#                 "ec2:Describe*",
#                 "elasticloadbalancing:Describe*",
#                 "logs:CreateLog*",
#                 "logs:PutLogEvents"
#             ],
#             "Resource": "*"
#         }
#     ]
# }
#

# Import AWS modules for python
import botocore
import boto3

# Import defaultdict module
from collections import defaultdict 

# Import JSON data handler
import json

# Import RegEx module
import re

def getPublicSubnets(region):
    publicSubnets = list()
    try:
        client = boto3.client('ec2', region_name=region)

        rtblResponse = dict()
        rtblResponse = client.describe_route_tables()

        snetResponse = dict()
        snetResponse = client.describe_subnets()

        vpcSubnets = defaultdict(list)
        
        for subnet in snetResponse['Subnets']:
            vpcSubnets[subnet['VpcId']].append(subnet['SubnetId'])
        
        #for vpc in vpcSubnets.items():
        #    print("The subnets per VPC are: ", vpc)

        candidateSubnets = list()

        # Identify public subnets by finding subnet route tables w/ Internet gateways
        for routeTable in rtblResponse['RouteTables']:
            
            #Add the explicitly associated subnets to public candidates list
            for association in routeTable['Associations']:
                if 'SubnetId' in association and association['SubnetId'] not in candidateSubnets:
                    candidateSubnets.append(association['SubnetId'])
                    #remove explicitly associated subnet from VPC's subnet consideration list
                    vpcSubnets[routeTable['VpcId']].remove(association['SubnetId'])
            
            #If this a Main route table add only implicitly associated subnets to public candidate list
            if routeTable['Associations'][0]['Main']:
                for implicitSubnet in vpcSubnets[routeTable['VpcId']]:
                    if implicitSubnet not in publicSubnets:
                        candidateSubnets.append(implicitSubnet)

            #Add all candidate subnets to public subnets list if route table has an IGW target route
            for route in routeTable['Routes']:
                if 'GatewayId' in route:
                    if re.search("^igw-", route['GatewayId']):
                        publicSubnets.extend(candidateSubnets)

            candidateSubnets.clear()
    
    except botocore.exceptions.ClientError as error:
        publicSubnets.clear()
        print("Boto3 API returned error: ", error)

    return(publicSubnets)



#Get ELB instance's associated subnet   
def getElbInstanceSubnet(elbArn, region):
    subnetIds = list()
    try:
        client = boto3.client('elbv2', region_name=region)
        response = client.describe_load_balancers(
            LoadBalancerArns=[
                elbArn
            ]
        )
    
    except botocore.exceptions.ClientError as error:
        print("Boto3 API returned error: ", error)
    
    for elb in response['LoadBalancers']:
        for az in elb['AvailabilityZones']:
            if re.search("^subnet-", az['SubnetId']):
                subnetIds.append(az['SubnetId'])
        
    return subnetIds
    
def lambda_handler(event, context):
    complianceValue = 'NOT_APPLICABLE'
    config = boto3.client('config')
    configEvent = json.loads(event['invokingEvent'])
    region = configEvent['configurationItem']['awsRegion']
    regionPublicInstances = list()
    resourceId = configEvent['configurationItem']['resourceId']
    arn = configEvent['configurationItem']['ARN']

    pubSubs = getPublicSubnets(region)
    
    myElbSubnets = getElbInstanceSubnet(arn, region) 
       
    if (configEvent['configurationItem']['resourceType'] != 'AWS::ElasticLoadBalancingV2::LoadBalancer'):
        complianceValue = 'NOT_APPLICABLE'
        print(configEvent)
    
    for elbSub in myElbSubnets:
        if elbSub in pubSubs:
            complianceValue = 'NON_COMPLIANT'
    
    if complianceValue == 'NON_COMPLIANT':
        print("ELB: {} in region: {} is {}".format(arn, region, complianceValue))
    else:
        complianceValue = 'COMPLIANT'
        print("ELB: {} in region: {} is {}".format(arn, region, complianceValue))
        

    response = config.put_evaluations(
       Evaluations=[
            {
                'ComplianceResourceType': configEvent['configurationItem']['resourceType'],
                'ComplianceResourceId': resourceId,
                'ComplianceType': complianceValue,
                'Annotation': 'Is this ELB instance in a public subnet?',
                'OrderingTimestamp': configEvent['configurationItem']['configurationItemCaptureTime']
            },
       ],
       ResultToken=event['resultToken']
       #TestMode=True
       )