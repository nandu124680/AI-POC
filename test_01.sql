-- migrations/001_create_users.sql
CREATE TABLE Users (
    UserID INT PRIMARY KEY,
    FirstName VARCHAR(100),
    Email_Address VARCHAR(255),
    createdAt TIMESTAMP
);