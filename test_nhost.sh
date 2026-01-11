#!/bin/bash
# Test Nhost connection

ENDPOINT="https://yobugvzhlfuxviaptquw.hasura.ap-south-1.nhost.run/v1/graphql"

echo "Enter your Nhost Admin Secret:"
read -r SECRET

echo ""
echo "Testing connection..."
echo ""

curl -X POST "$ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "x-hasura-admin-secret: $SECRET" \
  -d '{"query": "{ user_phone_no(limit: 3) { phone_no name } }"}'

echo ""
