import argparse
import logging
import sys
import requests
from natsort import natsorted

__version_info__ = ('19', '06', '0')
__version__ = '.'.join(__version_info__)

def main():

    def check_positive(value):
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
        return ivalue

    parser = argparse.ArgumentParser(prog='harbor-cleanup', description="Cleans up images in a Harbor project.")
    req_grp = parser.add_argument_group(title='required arguments')
    parser.add_argument('-d', '--debug', action='store_true', help="turn on debugging mode")
    parser.add_argument('-q', '--quiet', action='store_true', help="suppress console output")
    parser.add_argument('-n', '--dry-run', action='store_true', help="only print out image tags, do not do actual deletion")
    req_grp.add_argument('-i', '--url', required=True, type=str, help="URL of the Harbor instance")
    req_grp.add_argument('-u', '--user', required=True, type=str, help="valid Harbor user with proper access")
    req_grp.add_argument('-p', '--password', required=True, type=str, help="password for Harbor user")
    parser.add_argument('-c', '--preserve-count', type=check_positive, help="keep the last n number of image tags (by reverse alphanumerical order); defaults to 5", default=5)
    parser.add_argument('-k', '--keep-file', type=str, help="Do not delete images in this file (one record per image)")
    parser.add_argument('project', type=str, help="name of the Harbor project to clean")

    if len(sys.argv[1:])==0:
        parser.print_help()
        parser.exit()

    args = parser.parse_args()

    LOG_LEVEL = logging.INFO
    if args.debug:
        LOG_LEVEL = logging.DEBUG
    elif args.quiet:
        LOG_LEVEL = logging.CRITICAL

    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s : %(message)s', level=LOG_LEVEL)
    logger = logging.getLogger(__name__)

    HARBOR_URL = args.url
    PROJECT_NAME = args.project
    HARBOR_USER = args.user
    HARBOR_PASS = args.password
    PRESERVE_COUNT = args.preserve_count
    KEEP_FILE = args.keep_file

    def return_json(method, url):
        try:
            if method == 'GET':
                response = requests.get(url, auth=(HARBOR_USER, HARBOR_PASS))
                response.raise_for_status()
                return response.json()
            elif method == 'DELETE':
                response = requests.delete(url, auth=(HARBOR_USER, HARBOR_PASS))
                response.raise_for_status()
            else:
                logger.error('Invalid request method')
                sys.exit(1)
        except requests.exceptions.RequestException as e:
            logger.error("Error: {}".format(e))
            sys.exit(1)

    def get_project_id_by_project_name(project_name):
        logger.info('Retrieving project id for %s', project_name)
        projects = return_json('GET', HARBOR_URL+'/api/projects?project_name='+project_name)
        if project_name != projects[0]['name']:
            logger.error('No such project %s found.', project_name)
            sys.exit(1)
        project_id = str(projects[0]['project_id'])
        logger.info('Project ID is %s', project_id)
        return project_id

    def get_images_in_project(project_id):
        logger.info('Retrieving images in %s', PROJECT_NAME)
        images = return_json('GET', HARBOR_URL+'/api/repositories?project_id='+project_id)
        logger.info('Images: %s', images)
        return images

    def get_tags_from_image(image):
        logger.info('Retrieving tags for image %s', image)
        tags = return_json('GET', HARBOR_URL+'/api/repositories/tags?repo_name='+image)
        logger.info('Tags: %s', tags)
        return tags

    def get_digest_from_tag(image, tag):
        response = return_json('GET', HARBOR_URL+'/api/repositories/manifests?repo_name='+image+'&tag='+tag)
        digest = response['manifest']['config']['digest']
        return digest

    def delete_tag(image, tag, digest):
        if args.dry_run:
            logger.info('Would have deleted %s:%s %s', image, tag, digest)
        else:
            logger.info('Deleting %s:%s %s', image, tag, digest)
            return_json('DELETE', HARBOR_URL+'/api/repositories?repo_name='+image+'&tag='+tag)

    def get_tags_to_keep(keep_file):
        tags_to_keep = []
        if keep_file:
            logger.info("Reading list of items to keep from %s", keep_file)
            file = open(keep_file, 'r')
            for line in file:
                image,tag = line.strip().split(':')
                digest = get_digest_from_tag(image, tag)
                tags_to_keep.append(digest)
            file.close()
            logger.info("There are %s items to keep", len(tags_to_keep))
        return tags_to_keep

    PROJECT_ID = get_project_id_by_project_name(PROJECT_NAME)
    IMAGES = get_images_in_project(PROJECT_ID)
    IMAGES_TO_KEEP = get_tags_to_keep(KEEP_FILE)

    if not IMAGES:
        logger.info('No images found. Nothing to do.')
        sys.exit(0)

    for image in IMAGES:
        TAGS = natsorted(get_tags_from_image(image))
        if len(TAGS) > PRESERVE_COUNT:
            tags_to_delete = TAGS[:-PRESERVE_COUNT]
            for tag in tags_to_delete:
                try:
                    digest = get_digest_from_tag(image, tag)
                    if digest in IMAGES_TO_KEEP:
                        logger.warn('Keeping pinned image %s:%s %s', image, tag, digest)
                    else:
                        delete_tag(image, tag, digest)
                except:
                    logger.warn('Failed to remove %s:%s', image, tag)
            logger.info('%s cleaned successfully', image)
        else:
            logger.info('%s does not need to be cleaned up', image)

if __name__ == '__main__':
    main()
