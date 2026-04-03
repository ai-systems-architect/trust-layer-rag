variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "compliance"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  default     = "compliance_admin"
}

variable "db_password" {
  description = "PostgreSQL master password — set via TF_VAR_db_password, never hardcoded"
  type        = string
  sensitive   = true
}

variable "s3_bucket_name" {
  description = "S3 bucket for raw PDFs and processed chunks"
  type        = string
  default     = "governed-compliance-engine"
}

variable "project_tag" {
  description = "Project tag applied to all resources for cost tracking"
  type        = string
  default     = "governed-compliance-engine"
}
