export ENG_AI_MODEL_GW_KEY=sk-sO8931_TPV_2fvM9Bpq9YQ

curl -s -X GET "https://eng-ai-model-gateway.sfproxy.devx-preprod.aws-esvc1-useast2.aws.sfdc.cl/v1/models" \
  --header "Authorization: Bearer $ENG_AI_MODEL_GW_KEY" \
  --header 'Content-Type: application/json' | jq -r '.data[].id