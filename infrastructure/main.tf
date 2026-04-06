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
    name  = "rds.force_ssl"
    value = "1"
  }
}

# RDS Instance
resource "aws_db_instance" "compliance_rag" {
  identifier             = "governed-compliance-engine"
  engine                 = "postgres"
  engine_version         = "15"
  instance_class         = "db.t3.micro"
  allocated_storage      = 20
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
