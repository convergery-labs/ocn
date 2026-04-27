provider "aws" { region = "eu-north-1" }


resource "aws_s3_bucket" "tf_state" {
  bucket = "ocn-terraform-state"
}


resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration { status = "Enabled" }
}


resource "aws_dynamodb_table" "tf_lock" {
  name         = "ocn-terraform-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}