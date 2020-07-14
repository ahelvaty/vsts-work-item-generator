"""The VSTS Work Item Generator monitors an email inbox for ServiceNow Intake Requests and, upon detection, generates the respective work items in the VSTS DevOps (Azure DevOps) Environment."""
# Import the OS Module
import os

# Import the AWS S3 module
import boto3

# Import Decryption Module
from base64 import b64decode

# Import the IMAP and SMTP email client module
import imaplib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Import the datetime module
from datetime import datetime, timedelta

# Import the VstsClient module
from vstsclient.vstsclient import VstsClient
from vstsclient.models import JsonPatchDocument, JsonPatchOperation
from vstsclient.constants import SystemFields, LinkTypes
from vstsclient._http import HTTPError


# Class to communicate with customized back-end VSTS Kanban Setup
class GTSKanban(object):
    RITM = '/fields/GTSKanban.RITM'
    TASK = '/fields/GTSKanban.TASK'
    GBL = '/fields/GTSKanban.GBL'
    PYXIS = '/fields/GTSKanban.Pyxis'
    TARGET_ENV = '/fields/GTSKanban.TargetEnvironment'


# Accessing the AWS Lambda Environment Variables - concealing sensitive account information
# Normal Values
emailHostNameEnvVar = os.environ['emailHostName']
emailUserNameEnvVar = os.environ['emailUserName']
vstsWIAccountEnvVar = os.environ['vstsWIAccount']
TokChangeDateEnvVar = os.environ['TOKEN_CHANGE_DATE']
scEmailSearchEnvVar = os.environ['scEmailSearch']
senderEmailEnvVar = os.environ['senderEmailAddress']
recipientEmailEnvVar = os.environ['recipientEmailAddress']
smtpEmailUserNameEnvVar = os.environ['smtpEmailUserName']

# Encrypted Values
ENCRYPTED_emailPasswordEnvVar = os.environ['emailPassword']
ENCRYPTED_vstsWIAcTokenEnvVar = os.environ['vstsWIAcToken']

# Decrypted Values
DECRYPTED_emailPasswordEnvVar = boto3.client('kms').decrypt(CiphertextBlob=b64decode(ENCRYPTED_emailPasswordEnvVar))['Plaintext']
DECRYPTED_vstsWIAcTokenEnvVar = boto3.client('kms').decrypt(CiphertextBlob=b64decode(ENCRYPTED_vstsWIAcTokenEnvVar))['Plaintext']

# Decoded, Decrypted Values
emailPasswordEnvVar = DECRYPTED_emailPasswordEnvVar.decode("utf-8")
vstsWIAcTokenEnvVar = DECRYPTED_vstsWIAcTokenEnvVar.decode("utf-8")


# S3 Information #######
# AWS S3 Bucket Connection Information
bucket_name = "S3_BUCKET_NAME_HERE"
s3 = boto3.resource("s3")

# .txt File with ID Number
file_name_idNum = "workItemIDNumber.txt"
s3_path_idNum = file_name_idNum
lambda_path_idNum = "/tmp/" + file_name_idNum

# .txt File with Last Send Date of Reminder Email to Change VSTS Token
file_name_emailSendDate = "TokenEmailSendDate.txt"
s3_path_emailSendDate = file_name_emailSendDate
lambda_path_emailSendDate = "/tmp/" + file_name_emailSendDate


# VSTS Work Item Card Creation Variables #######
# Project Names
Project_GTS = "Architecture"

# Work item types
REQUEST = "Request"
PBI = "Product Backlog Item"


def s3_Read_Str_from_TXT_File(bucket_name, s3_pathToFile):
    """
    Reads file contents (work ID Number) from AWS S3 Bucket to
    determine what ID Number to begin the iteratation process on.

    Parameters:
    ----------
    bucket_name : str
        AWS S3 Storage Bucket Name
    s3_pathToFile : str
        Path to reach file

    Returns:
    ----------
    workIDNumber: Int
    """

    obj = s3.Object(bucket_name, s3_pathToFile)
    contents = obj.get()['Body'].read().decode('utf-8')

    return contents


def s3_Write_IDNum_To_TXT_File(bucket_name, s3_pathToFile, workIDNumber):
    """
    Writes the most recent work id number back to the S3 Bucket

    Parameters:
    ----------
    bucket_name : str
        AWS S3 Storage Bucket Name
    s3_pathToFile : str
        Path to reach file
    IDNum : int
    ----------

    Returns:
    ----------
    Successful write of IDNum to .txt file
    ----------
    """
    idNumToString = str(workIDNumber)
    encoded_idNum = idNumToString.encode("utf-8")
    s3.Bucket(bucket_name).put_object(Key=s3_pathToFile, Body=encoded_idNum)


def s3_Write_Str_To_TXT_File(bucket_name, s3_pathToFile, strToWrite):
    """
    Writes the input string to the input S3 Bucket

    Parameters:
    ----------
    bucket_name : str
        AWS S3 Storage Bucket Name
    s3_pathToFile : str
        Path to reach file
    strToWrite : str
    ----------

    Returns:
    ----------
    Successful write of 'strToWrite' to .txt file
    ----------
    """
    strToWrite = str(strToWrite)
    encoded_str = strToWrite.encode("utf-8")
    s3.Bucket(bucket_name).put_object(Key=s3_pathToFile, Body=encoded_str)


def dateDifCalculator(dateStrFormat):
    """
    This function calculates the number of days since the input date

    Parameters:
    ----------
    TokChangeDateEnvVar : str
        Example: "Year: 2018 Month: 7 Day: 21"
            Function will filter out the Year, Month, and Day as Integers

    Returns:
    ----------
    daysSinceChangeInteger : Integer
    """
    YearMonthDayRaw = dateStrFormat

    dayFiltered = YearMonthDayRaw.split("Day:")[1].strip()
    YearMonthRaw = YearMonthDayRaw.split("Day:")[0].strip()
    day = int(dayFiltered)
    print(day)

    MonthFiltered = YearMonthRaw.split("Month:")[1].strip()
    YearRaw = YearMonthRaw.split("Month:")[0].strip()
    month = int(MonthFiltered)
    print(month)

    YearFiltered = YearRaw.split("Year:")[1].strip()
    year = int(YearFiltered)
    print(year)

    tokenChangeDate = datetime(year, month, day)
    daysSinceChangeObject = abs(datetime.now() - tokenChangeDate)
    print(daysSinceChangeObject)

    daysSinceChangeInteger = int(daysSinceChangeObject.days)

    return daysSinceChangeInteger


def tokenChangeAlarm(dateDifInt):
    """
    This function determines whether or not an email reminder needs to be sent to change the VSTS Account Token:
        when the token has been unchanged for 330 days a warning will need to be issued to have it changed soon

    Parameters:
    ----------
    dateDifInt : int
        Example: 151

    Returns:
    ----------
    NeedToSendEmail : Boolean
    """
    if dateDifInt >= 330:
        NeedToSendEmail = True
    else:
        NeedToSendEmail = False

    daysSinceChangeString = str(dateDifInt)
    print("The token was last changed " + daysSinceChangeString + " days ago.")

    return NeedToSendEmail


def sendEmail(emailHost, emailUserName, emailPassword, senderEmailAddress, recipientEmailAddress, emailSubject, emailBody):
    """
    This function sends an email.

    Parameters:
    ----------
    emailHost : str
    emailUserName : str
    emailPassword : str
    senderEmailAddress : str
    recipientEmailAddress : str
    emailSubject : str
    emailBody : str

    Returns:
    ----------
    None
    """

    msg = MIMEMultipart()
    msg['From'] = senderEmailAddress
    msg['To'] = recipientEmailAddress
    msg['Subject'] = emailSubject
    message = emailBody
    msg.attach(MIMEText(message))

    # establish SMTP mail server object over port 587, later to be secured with TLS encryption
    mailserver = smtplib.SMTP(emailHost, 587)
    # identify ourselves to smtp mail client
    mailserver.ehlo()
    # secure our email with tls encryption
    mailserver.starttls()
    # re-identify ourselves as an encrypted connection
    mailserver.ehlo()
    # login to mail server account
    mailserver.login(emailUserName, emailPassword)
    # send email
    mailserver.sendmail(senderEmailAddress, recipientEmailAddress, msg.as_string())
    # disconnect from the mail server
    mailserver.quit()


def email_Connection(emailHost, emailUserName, emailPassword, mailbox):
    """
    Establishes connection to email client,
    logs into the Email account,
    connects to the mailbox

    Parameters:
    ----------
    emailHost: str
    emailUserName : str
    emailPassword : str
    mailbox : str
    ----------

    Returns:
    ----------
    Successful connection to to email account and mailbox
    ----------
    """
    mail = imaplib.IMAP4_SSL(emailHost)  # email host name

    # Email account credentials
    mail.login(emailUserName, emailPassword)  # email username and password

    # Connect to mailbox.
    mail.select(mailbox)

    return mail


def email_Disconnect(mail):
    """
    Disconnects from the email account by closing the active mailbox and shutting down connection to the server (logging out)
    """
    # Close currently selected mailbox - Deleted messages are removed from writable mailbox
    mail.close()
    # Shutdown connection to server
    mail.logout()


def VSTS_Client_Connection(vstsAccount, vstsAccountToken):
    """
    Logs into the VSTS account

    Parameters:
    ----------
    vstsAccount : str
    vstsAccountToken : str
    ----------

    Returns:
    ----------
    Successful client connection to to VSTS account
    ----------
    """
    client_GTS = VstsClient(vstsAccount, vstsAccountToken)

    return client_GTS


def Email_Search(mail, emailAddressToSearch, numDaysToSearchBeforeToday=0):
    """
    Default:
    Searches all emails from the current day's date,
    creates a list of email uids of all the emails matching the search criteria

    Parameters:
    ----------
    mail : object
    emailAddressToSearch : str
    numDaysToSearchBeforeToday : int
        Default : 0 -> Searches the current date only
                > 0 -> Searches that many days before the current date
                Example:
                    numDaysToSearchBeforeToday = 1
                    returns uids from yesterday

                    numDaysToSearchBeforeToday = 2
                    returns uids from 2 days ago
    ----------

    Returns:
    ----------
    List of UIDs that match search criteria
    """

    i = 0
    listOfUIDLists = []
    FullUIDListRaw = []
    # Creates list of Email ID Numbers
    while i <= numDaysToSearchBeforeToday:
        # Creates the date-based search criteria
        date_search = datetime.strftime(datetime.now() - timedelta(i), "%d %b %Y")
        uidListRaw = list(mail.uid('search', None, '(HEADER From \"<' + emailAddressToSearch + '>\")', '(HEADER Date ' + '\"' + date_search + '\"' + ')'))[1][0].decode("utf-8")
        uidListCooked = uidListRaw.split(" ")
        listOfUIDLists.append(uidListCooked)
        i += 1

    # Searches and prints all email uids in mailbox
    allUIDs = mail.uid('search', None, "ALL")  # search and return uids instead
    print("\nAll UIDs:")
    print(allUIDs)

    # Searches for Unread messages
    unread = mail.search(None, '(UNSEEN)')
    print("UNREAD MESSAGES:")
    print(unread)

    # Searches and prints all email uids in mailbox from SC email
    scUIDs = mail.search(None, '(HEADER From \"<' + emailAddressToSearch + '>\")')
    print("\nSC UIDs:")
    print(scUIDs)

    # Concatenates the 'Today' and 'Yesteday' email ID lists
    for uidList in listOfUIDLists:
        FullUIDListRaw = FullUIDListRaw + uidList
    print("\nFullUIDListRaw:")
    print(FullUIDListRaw)

    # Filters Null elements out of the concatenated list
    FullUIDListFiltered = list(filter(lambda a: a != '', FullUIDListRaw))
    print("\nFullUIDListFiltered:")
    print(FullUIDListFiltered)

    return FullUIDListFiltered


def messageData(mail, UIDNum):
    """
    Acquire the Email Inbox Number for Current Message from UIDNum (for deletion of the email after processing),
    Acquire message data, Obtain Message Subject, then process and filter

    Parameters:
    ----------
    mail : object
        IMAP Email Account Connection
    UIDNum : String
        Email Message ID Number

    Returns:
    ----------
    emailInboxNumAsBytes : byte
        For deletion of message
    Subject : str
        For creation of Work Item Card
    filtered_body : str
        For creation of Work Item Card
    """
    # Acquires message data as tuple
    data = mail.uid('fetch', UIDNum, '(RFC822)')
    print(data)
    if data[0] == "OK":
        # Acquire the Email Inbox Number for Current Message for later deletion - Literally what number
        # (1 through 'Number of emails') email (in order from oldest to newest) this is in the Inbox
        emailInboxNum = data[1][0][0].decode("utf-8").split(" ")[0]
        # Acquire email contents for processing
        raw_email = data[1][0][1].decode("utf-8")
    else:
        # Acquire the Email Inbox Number for Current Message for later deletion - Literally what number
        # (1 through 'Number of emails') email (in order from oldest to newest) this is in the Inbox
        emailInboxNum = data[0][0].decode("utf-8").split(" ")[0]
        # Acquire email contents for processing
        raw_email = data[0][1].decode("utf-8")
    emailInboxNumAsBytes = bytes(emailInboxNum, 'utf-8')
    body_email = raw_email.split("MIME-Version: 1.0")[1]
    Subject = raw_email.split("Subject: ")[1].split("Content-Type: ")[0]
    # Leave the final, filtered body with HTML tags for formatting purposes
    filtered_body = body_email.replace("=", "").replace("\r", "").replace("\n", "").replace("\t", "")

    return emailInboxNumAsBytes, Subject, filtered_body


def WICardData(filtered_body, Subject):
    """
    Generate data for VSTS Work Item Card

    Parameters:
    ----------
    filtered_body : str
        Filtered body of email message
    Subject : str
        Subject of email message

    Returns:
    ----------
    TITLE, DESCRIPTION, TASK, GBL_Exists, GBL, PYXIS_Exists, PYXIS : tuple
        Tuple of all the data needed for the Work ID Card JSON Document
    """
    # Description for VSTS Work Item
    DESCRIPTION = filtered_body
    # Title for VSTS Work Item
    try:
        TITLE = filtered_body.split("Request Name: ")[1].split("<br>")[0]
    except IndexError:
        TITLE = "NEW VSTS WORK ITEM"
    # GBL Number for VSTS Work Item
    if filtered_body.find("GBL#: ") > -1:
        GBL = filtered_body.split("GBL#: ")[1].split("<br>")[0]
        GBL_Exists = True
    else:
        GBL_Exists = False
    # Pyxis Number for VSTS Work Item
    if filtered_body.find("PyxIS#: ") > -1:
        PYXIS = filtered_body.split("PyxIS#: ")[1].split("<br>")[0]
        PYXIS_Exists = True
    else:
        PYXIS_Exists = False
    # TASK Number for VSTS Work Item
    TASK = Subject.split("TASK")[1].split(" ")[0]

    return TITLE, DESCRIPTION, TASK, GBL_Exists, GBL, PYXIS_Exists, PYXIS


def createJsonWIDoc(WICardDataTuple):
    """
    Creates JSON Patch Document for VSTS Work ID Card Creation

    Parameters:
    ----------
    WICardDataTuple : tuple
        Tuple of all the data needed for the Work ID Card JSON Document

    Returns:
    ----------
    doc : object
        JSON Patch Document for VSTS Work ID Card Creation
    """
    # Work ID Tuple Elements for JSON Patch Document
    TITLE = WICardDataTuple[0]
    DESCRIPTION = WICardDataTuple[1]
    TASK = WICardDataTuple[2]
    GBL_Exists = WICardDataTuple[3]
    GBL = WICardDataTuple[4]
    PYXIS_Exists = WICardDataTuple[5]
    PYXIS = WICardDataTuple[6]

    # Create a JsonPatchDocument and provide the values for the work item fields
    doc = JsonPatchDocument()
    doc.add(JsonPatchOperation('add', SystemFields.TITLE, TITLE))
    doc.add(JsonPatchOperation('add', SystemFields.DESCRIPTION, DESCRIPTION))
    # doc.add(JsonPatchOperation('add', GTSKanban.RITM, RITM))
    doc.add(JsonPatchOperation('add', GTSKanban.TASK, TASK))
    AreaPath = 'GTS Architecture\\Architecture'
    doc.add(JsonPatchOperation('add', SystemFields.AREA_PATH, AreaPath))
    if GBL_Exists:
        doc.add(JsonPatchOperation('add', GTSKanban.GBL, GBL))
    if PYXIS_Exists:
        doc.add(JsonPatchOperation('add', GTSKanban.PYXIS, PYXIS))

    return doc


def parentToChildConnection(vstsClient, workIDNumber, WICardDataTuple):
    """
    Iterates through the work items to find the 2 that were just created in order to create the parent/child connection.

    There are a few ways to shorten this code and combine blocks and snippets. I have them separated for debugging. I have different 'checks'
    in place to help with confirming the exact issue.

    Parameters:
    ----------
    workIDNumber : int
        Read from S3 Bucket -> Last Work Item to be created
    WICardDataTuple : tuple
        Tuple of all the data needed for the Work ID Card JSON Document

    Returns:
    ----------
    Successful Creation of Work Item Parent/Child Connection
    """
    TASK = WICardDataTuple[2]
    i = workIDNumber
    foundREQUEST = False
    foundPBI = False
    while foundREQUEST is False or foundPBI is False:
        try:
            checkingWI = vstsClient.get_workitem(i)
            workItemExists = True
            print(checkingWI)
        except HTTPError:
            workItemExists = False
            print("Passed - HTTPError Exception: Workitem " + str(i) + " does not exist")
            pass
        if workItemExists:
            try:
                if "GTSKanban.TASK" in checkingWI.fields:
                    if checkingWI.fields["GTSKanban.TASK"] == TASK:
                        if checkingWI.fields["System.WorkItemType"] == REQUEST or foundREQUEST is False:
                            foundREQUEST = True
                            print("\t" + "\t" + "We found the REQUEST Work Item")
                            REQUEST_WIID = checkingWI.fields["System.Id"]
                        elif checkingWI.fields["System.WorkItemType"] == PBI or foundPBI is False:
                            foundPBI = True
                            print("\t" + "\t" + "We found the PBI Work Item")
                            PBI_WIID = checkingWI.fields["System.Id"]
                        print("\t" + "\t" + str(checkingWI.fields["System.Id"]))
                        print("\t" + "\t" + checkingWI.fields["GTSKanban.TASK"])
                        print("\t" + "\t" + checkingWI.fields["System.Title"])
                        # write the most recent work id number back to the S3 Bucket
                        # the purpose of this block of code is to save the most recent work item ID number in an S3 bucket, this way
                        # when the program is run it does not have to iterate from a set start ID number in the program, but the last
                        # ID number called in the program. This matters for both efficiency and the time it takes for the program to complete.
                        # Since the AWS Lambda function will timeout after 15 minutes, it's important to have the program finish as quickly as possible.
                        s3_Write_IDNum_To_TXT_File(bucket_name, s3_path_idNum, checkingWI.fields["System.Id"])
                    else:
                        print(checkingWI.fields["System.Id"])
                        if "GTSKanban.TASK" in checkingWI.fields:
                            print("\t" + checkingWI.fields["GTSKanban.TASK"])
                else:
                    print(checkingWI.fields["System.Id"])
                    if "GTSKanban.TASK" in checkingWI.fields:
                        print("\t" + checkingWI.fields["GTSKanban.TASK"])
            except UnboundLocalError:
                print("Passed - UnboundLocalError Exception: Workitem " + str(i) + " does not exist")
                pass
        i = i + 1

    request_WorkItemData = vstsClient.get_workitem(REQUEST_WIID)
    pbi_WorkItemData = vstsClient.get_workitem(PBI_WIID)
    # Create parent/child link between [Request (parent)] and [Product Backlog Item (child)]
    vstsClient.add_link(pbi_WorkItemData.id, request_WorkItemData.id, LinkTypes.PARENT, "Parent/Child connection created automatically")


def lambda_handler(event, context):
    # Establish connection to mail server, login to account, and select INBOX to be working mailbox
    mail = email_Connection(emailHostNameEnvVar, emailUserNameEnvVar, emailPasswordEnvVar, "INBOX")

    # Initialize the VSTS client using the VSTS instance and personal access token
    # *******THIS TOKEN NEEDS TO BE REPLACED/RENEWED/UPDATED YEARLY*******
    client_GTS = VstsClient(vstsWIAccountEnvVar, vstsWIAcTokenEnvVar)  # account instance + account token
    print(client_GTS)

    # Search the INBOX for emails from SC from the current day's date and previous day's date
    UID_List = Email_Search(mail, scEmailSearchEnvVar, 3)

    # Iterates through list of qualifying UIDs, extracts message data, moves message from Inbox to Archive,
    # creates Work ID Cards, reads/writes VSTS Work Item ID Number from/to S3 bucket, creates parent/child
    # connection between respective Work ID Cards
    for UIDNum in UID_List:
        emailInboxNumAsBytes, Subject, filtered_body = messageData(mail, UIDNum)
        # Checks to make sure the message is an Intake Request
        if Subject[:4] == "TASK":
            # Steps to Move a copy of SC Email to 'Archive/ServiceCafe' Folder - copy, store, expunge
            # creates a copy of the current SC Email in the 'Archive/ServiceCafe' Folder
            mail.copy(emailInboxNumAsBytes, 'Archive/ServiceCafe')
            print('copied')
            # Sets a flag for the original message to be deleted
            mail.store(emailInboxNumAsBytes, '+FLAGS', '\\Deleted')
            print('flagged')
            # Deletes all messages with the 'Delete' flag
            mail.expunge()
            print('deleted')

            # Generate data for VSTS Work Item Card as a Tuple
            WICardDataTuple = WICardData(filtered_body, Subject)

            # Creates JSON Patch Document for VSTS Work ID Card Creation
            WIJsonPatchDoc = createJsonWIDoc(WICardDataTuple)
            print("JSON Patch Document Created")
            print('\n')
            print(WIJsonPatchDoc)
            print('\n')

            # Create a new work item - REQUEST Card - by specifying the project and work item type
            new_WorkitemREQUEST = client_GTS.create_workitem(
                Project_GTS,                                # Working Team project name
                REQUEST,                                    # Work item type (e.g. Epic, Feature, User Story etc.)
                WIJsonPatchDoc)                             # JsonPatchDocument with operations
            # Create a new work item - PBI (Product Backlog Item) Card - by specifying the project and work item type
            new_WorkitemPBI = client_GTS.create_workitem(
                Project_GTS,                                # Working Team project name
                PBI,                                        # Work item type (e.g. Epic, Feature, User Story etc.)
                WIJsonPatchDoc)                             # JsonPatchDocument with operations

            # read file contents from AWS S3 Bucket to determine what ID Number to begin the iteratation process on
            workIDNumber = int(s3_Read_Str_from_TXT_File(bucket_name, s3_path_idNum))
            print(workIDNumber)

            # iterates through the work items and creates a parent/child connection between the 2 that were just created
            parentToChildConnection(client_GTS, workIDNumber, WICardDataTuple)

    # Closes the active mailbox (INBOX) and shuts down connection to the server (logs out)
    email_Disconnect(mail)

    # this block of code checks the 'TOKEN_CHANGE_DATE' Environment Variable to see if an alert email needs to be sent out, then,
    # if an alert does need to be sent, it checks to see the most recent time one was sent. If it was sent more than two days ago
    # another email is sent. This occurs until the 'TOKEN_CHANGE_DATE' and the 'vstsWIAcToken' Environment Variables are updated.
    tokenChangedDays = dateDifCalculator(TokChangeDateEnvVar)
    if tokenChangeAlarm(tokenChangedDays):
        dateLastEmailAlertSent = s3_Read_Str_from_TXT_File(bucket_name, s3_path_emailSendDate)
        print(dateLastEmailAlertSent)
        if dateDifCalculator(dateLastEmailAlertSent) > 2:
            # VSTS Token Replacement Alert Email Creation:
            # - subject and body for alert email
            emailAlertSubject = "VSTS Account Token Change Alert!"
            emailAlertBody = "The Login Token for the Visual Studio Team Services (VSTS) Work Item Generator will be expiring soon. It is PERTINENT that the token be regenerated and updated in the Environment Variables section of the AWS (US East (Ohio) region) Lambda Function, \"VSTSWorkItemGenerator\".\n\n Environment Variables requiring an update:\n\n - vstsWIAcToken : contains the VSTS account token \n - TOKEN_CHANGE_DATE : contains the date on which the VSTS account token was updated\n\nSee VSTS_Work_Item_Generator Documentation for instructions on how to perform this update."
            # sends email alert to the respective recipient(s)
            sendEmail(emailHostNameEnvVar, smtpEmailUserNameEnvVar, emailPasswordEnvVar, senderEmailEnvVar, recipientEmailEnvVar, emailAlertSubject, emailAlertBody)
            print("Email sent. It has been more than 3 days since the last email was sent.")
            # generates a string that contains the date the email alert was just sent on
            emailSendDate = "Year: " + str(datetime.now().year) + " Month: " + str(datetime.now().month) + " Day: " + str(datetime.now().day)
            # writes the email send date string to the S3 contained .txt file
            s3_Write_Str_To_TXT_File(bucket_name, s3_path_emailSendDate, emailSendDate)
        else:
            print("Email not sent. It has not been more than 3 days since the last email was sent.")
