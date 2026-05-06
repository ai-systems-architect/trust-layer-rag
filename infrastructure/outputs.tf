output "rds_endpoint" {
  description = "RDS instance endpoint — add to .env as RDS_ENDPOINT"
  value       = aws_db_instance.compliance_rag.endpoint
}

output "rds_port" {
  description = "RDS instance port"
  value       = aws_db_instance.compliance_rag.port
}

output "s3_bucket_name" {
  description = "S3 bucket name — add to .env as S3_BUCKET"
  value       = aws_s3_bucket.corpus.bucket
}

output "db_name" {
  description = "PostgreSQL database name — add to .env as RDS_DB_NAME"
  value       = var.db_name
}

output "db_username" {
  description = "PostgreSQL master username — add to .env as RDS_USER"
  value       = var.db_username
}

output "bedrock_guardrail_id" {
  description = "Bedrock guardrail ID — add to .env as BEDROCK_GUARDRAIL_ID"
  value       = aws_bedrock_guardrail.compliance.guardrail_id
}
