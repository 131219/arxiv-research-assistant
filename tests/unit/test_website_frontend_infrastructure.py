from pathlib import Path

import yaml


TEMPLATE_PATH = Path(
    "infrastructure/cloudformation/templates/website-frontend.yaml"
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


def test_frontend_stack_defines_private_s3_and_cloudfront_resources():
    template = load_template()
    resources = template["Resources"]

    assert resources["FrontendBucket"]["Type"] == "AWS::S3::Bucket"
    assert resources["FrontendBucketPolicy"]["Type"] == "AWS::S3::BucketPolicy"
    assert (
        resources["FrontendOriginAccessControl"]["Type"]
        == "AWS::CloudFront::OriginAccessControl"
    )
    assert (
        resources["FrontendDistribution"]["Type"]
        == "AWS::CloudFront::Distribution"
    )


def test_frontend_bucket_blocks_all_public_access():
    template = load_template()

    public_access = template["Resources"]["FrontendBucket"]["Properties"][
        "PublicAccessBlockConfiguration"
    ]

    assert public_access == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }


def test_cloudfront_default_behavior_serves_s3_over_https():
    template = load_template()

    config = template["Resources"]["FrontendDistribution"]["Properties"][
        "DistributionConfig"
    ]
    behavior = config["DefaultCacheBehavior"]

    assert behavior["TargetOriginId"] == "FrontendS3Origin"
    assert behavior["ViewerProtocolPolicy"] == "redirect-to-https"


def test_cloudfront_routes_api_requests_to_alb():
    template = load_template()

    config = template["Resources"]["FrontendDistribution"]["Properties"][
        "DistributionConfig"
    ]

    api_behavior = next(
        behavior
        for behavior in config["CacheBehaviors"]
        if behavior["PathPattern"] == "/api/*"
    )

    assert api_behavior["TargetOriginId"] == "ApiAlbOrigin"
    assert api_behavior["ViewerProtocolPolicy"] == "redirect-to-https"


def test_cloudfront_api_behavior_disables_caching():
    template = load_template()

    config = template["Resources"]["FrontendDistribution"]["Properties"][
        "DistributionConfig"
    ]

    api_behavior = next(
        behavior
        for behavior in config["CacheBehaviors"]
        if behavior["PathPattern"] == "/api/*"
    )

    assert (
        api_behavior["CachePolicyId"]
        == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    )


def test_cloudfront_api_behavior_forwards_authorization():
    template = load_template()

    config = template["Resources"]["FrontendDistribution"]["Properties"][
        "DistributionConfig"
    ]

    api_behavior = next(
        behavior
        for behavior in config["CacheBehaviors"]
        if behavior["PathPattern"] == "/api/*"
    )

    assert (
        api_behavior["OriginRequestPolicyId"]
        == "216adef6-5c7f-47e4-b989-5492eafa07d3"
    )


def test_cloudfront_spa_fallback_routes_403_and_404_to_index():
    template = load_template()

    config = template["Resources"]["FrontendDistribution"]["Properties"][
        "DistributionConfig"
    ]

    responses = {
        response["ErrorCode"]: response
        for response in config["CustomErrorResponses"]
    }

    for code in (403, 404):
        assert responses[code]["ResponseCode"] == 200
        assert responses[code]["ResponsePagePath"] == "/index.html"


def test_frontend_stack_exports_distribution_and_bucket_outputs():
    template = load_template()
    outputs = template["Outputs"]

    assert "FrontendBucketName" in outputs
    assert "DistributionId" in outputs
    assert "DistributionDomainName" in outputs


def test_bucket_policy_cloudfront_source_arn_has_no_trailing_whitespace():
    template = load_template()

    policy = template["Resources"]["FrontendBucketPolicy"]["Properties"][
        "PolicyDocument"
    ]
    statement = policy["Statement"][0]

    source_arn = statement["Condition"]["StringEquals"]["AWS:SourceArn"]

    assert source_arn == source_arn.strip()
    assert source_arn == (
        "arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:"
        "distribution/${FrontendDistribution}"
    )
