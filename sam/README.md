# Deployment

Inside template directory:

## Build

```
sam build
```

## Deploy

```
sam deploy \
    --resolve-s3 \
    --stack-name iot-lambda-client \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides AccountID=${AccountID} Region=${Region} LambdaIoTCoreEndpoint=a3iimiyjvdbguz-ats.iot.eu-west-1.amazonaws.com LambdaIoTClientID=invocation_client
```