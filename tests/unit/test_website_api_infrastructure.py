from pathlib import Path

import yaml


TEMPLATE_PATH = Path(
    "infrastructure/cloudformation/templates/website-api.yaml"
)


class CloudFormationLoader(yaml.SafeLoader):
    pass


def cloudformation_constructor(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)

    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)

    return loader.construct_mapping(node)


for tag in (
    "!Ref",
    "!Sub",
    "!GetAtt",
):
    CloudFormationLoader.add_constructor(
        tag,
        cloudformation_constructor,
    )


def load_template():
    return yaml.load(
        TEMPLATE_PATH.read_text(),
        Loader=CloudFormationLoader,
    )


def test_website_api_stack_defines_dedicated_runtime_resources():
    template = load_template()
    resources = template["Resources"]

    assert resources["ApiRepository"]["Type"] == "AWS::ECR::Repository"
    assert resources["ApiCluster"]["Type"] == "AWS::ECS::Cluster"
    assert resources["ApiTaskDefinition"]["Type"] == "AWS::ECS::TaskDefinition"
    assert resources["ApiService"]["Type"] == "AWS::ECS::Service"
    assert (
        resources["ApiLoadBalancer"]["Type"]
        == "AWS::ElasticLoadBalancingV2::LoadBalancer"
    )
    assert (
        resources["ApiTargetGroup"]["Type"]
        == "AWS::ElasticLoadBalancingV2::TargetGroup"
    )


def test_api_tasks_are_not_directly_exposed_to_the_internet():
    template = load_template()
    resources = template["Resources"]

    api_ingress = resources["ApiSecurityGroup"]["Properties"][
        "SecurityGroupIngress"
    ]

    assert api_ingress == [
        {
            "IpProtocol": "tcp",
            "FromPort": 8080,
            "ToPort": 8080,
            "SourceSecurityGroupId": "AlbSecurityGroup",
        }
    ]


def test_api_service_uses_fargate_and_public_ip_for_beta_networking():
    template = load_template()

    service = template["Resources"]["ApiService"]["Properties"]

    assert service["LaunchType"] == "FARGATE"

    network = service["NetworkConfiguration"]["AwsvpcConfiguration"]

    assert network["AssignPublicIp"] == "ENABLED"


def test_api_task_uses_current_application_environment_variables():
    template = load_template()

    container = template["Resources"]["ApiTaskDefinition"]["Properties"][
        "ContainerDefinitions"
    ][0]

    names = {
        entry["Name"]
        for entry in container["Environment"]
    }

    assert "BEDROCK_KNOWLEDGE_BASE_ID" in names
    assert "BEDROCK_SYNTHESIS_MODEL_ID" in names
    assert "COGNITO_USER_POOL_ID" in names
    assert "COGNITO_APP_CLIENT_ID" in names
    assert "CONVERSATION_TABLE_NAME" in names
    assert "RESEARCH_RATE_LIMIT_TABLE_NAME" in names

    assert "BEDROCK_MODEL_ID" not in names


def test_api_target_group_uses_ip_targets_and_health_endpoint():
    template = load_template()

    target_group = template["Resources"]["ApiTargetGroup"]["Properties"]

    assert target_group["TargetType"] == "ip"
    assert target_group["Port"] == 8080
    assert target_group["HealthCheckPath"] == "/health"


def test_api_task_role_has_required_bedrock_runtime_permissions():
    template = load_template()

    policies = template["Resources"]["ApiTaskRole"]["Properties"]["Policies"]
    statements = policies[0]["PolicyDocument"]["Statement"]

    invoke_statement = next(
        statement
        for statement in statements
        if statement.get("Sid") == "InvokeSynthesisModel"
    )

    actions = set(invoke_statement["Action"])

    assert "bedrock:InvokeModel" in actions
    assert "bedrock:InvokeModelWithResponseStream" in actions
    assert "bedrock:GetInferenceProfile" in actions

def test_alb_ingress_is_restricted_to_cloudfront_origin_facing_prefix_list():
    template = load_template()

    parameters = template["Parameters"]

    assert "CloudFrontOriginFacingPrefixListId" in parameters

    ingress = template["Resources"]["AlbSecurityGroup"]["Properties"][
        "SecurityGroupIngress"
    ]

    assert ingress == [
        {
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "SourcePrefixListId": "CloudFrontOriginFacingPrefixListId",
        }
    ]

    assert all("CidrIp" not in rule for rule in ingress)
