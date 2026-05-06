# RDS Security Group — open on 5432, SSL is the security layer
resource "aws_security_group" "rds" {
  name        = "governed-compliance-rds-sg"
  description = "RDS access - SSL enforced, public corpus only"

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Open - Streamlit on GCP requires public endpoint. SSL enforced at param group level."
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# RDS Parameter Group — enforce SSL
resource "aws_db_parameter_group" "ssl_required" {
  name   = "governed-compliance-ssl"
  family = "postgres15"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
}

# RDS Instance
resource "aws_db_instance" "compliance_rag" {
  identifier             = "governed-compliance-engine"
  engine                 = "postgres"
  engine_version         = "15"
  instance_class         = var.db_instance_class
  allocated_storage      = 20
  db_name                = var.db_name
  username               = var.db_username
  password               = var.db_password
  publicly_accessible    = true
  parameter_group_name   = aws_db_parameter_group.ssl_required.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = true

  tags = {
    Project     = var.project_tag
    Environment = "portfolio"
    CostCenter  = "portfolio"
  }
}

# S3 Bucket — raw PDFs and processed chunks
resource "aws_s3_bucket" "corpus" {
  bucket = var.s3_bucket_name

  tags = {
    Project     = var.project_tag
    Environment = "portfolio"
    CostCenter  = "portfolio"
  }
}

# Block all public access — IAM controls access
resource "aws_s3_bucket_public_access_block" "corpus" {
  bucket = aws_s3_bucket.corpus.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Bedrock Guardrail — input prompt-attack filter + output contextual grounding
# Adopted into Terraform via `terraform import` after originally being created
# out-of-band. Keep attributes aligned with the live policy so plan stays clean.
# see docs/decision_log.md DL-022
resource "aws_bedrock_guardrail" "compliance" {
  name                      = "governed-compliance-guardrail"
  description               = "Prevents overclaiming in federal compliance responses"
  blocked_input_messaging   = "This query cannot be processed under the compliance assistant policy."
  blocked_outputs_messaging = "This response was blocked — the answer could not be grounded in the retrieved compliance documents."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
  }

  contextual_grounding_policy_config {
    filters_config {
      type      = "GROUNDING"
      threshold = 0.7
    }
    filters_config {
      type      = "RELEVANCE"
      threshold = 0.7
    }
  }
}
