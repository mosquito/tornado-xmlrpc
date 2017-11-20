# encoding: utf-8
import logging
import sys
from tornado.gen import coroutine, Return
from tornado.web import RequestHandler, HTTPError
from lxml import etree
from collections import OrderedDict
from .common import get_schema, xml2py, py2xml


if sys.version_info >= (3, 5):
    from asyncio import coroutine as make_coroutine
else:
    from tornado.gen import coroutine as make_coroutine


log = logging.getLogger(__name__)


class XMLRPCHandler(RequestHandler):
    METHOD_PREFIX = "rpc_"
    DEBUG = False

    @coroutine
    def _rpc_execute(self, method, *args, **kwargs):
        raise Return((yield make_coroutine(method)(*args, **kwargs)))

    @coroutine
    def _resolve_method(self, method_name):
        name = "{0}{1}".format(self.METHOD_PREFIX, method_name)
        method = getattr(self, name, None)

        if not callable(method):
            log.warning("Can't find method %s%s in ",
                        self.METHOD_PREFIX,
                        method_name,
                        self.__class__.__name__)

            raise HTTPError(404)

        return method

    @coroutine
    def _check_request(self):
        if 'xml' not in self.request.headers.get('Content-Type', ''):
            raise HTTPError(400)

    @coroutine
    def _parse_request(self):
        try:
            raise Return(self._parse_xml(self.request.body))
        except etree.XMLSyntaxError:
            raise HTTPError(400)

    def _format_response(self, response):
        root = etree.Element("methodResponse")
        el_params = etree.Element("params")
        el_param = etree.Element("param")
        el_value = etree.Element("value")
        el_param.append(el_value)
        el_params.append(el_param)
        root.append(el_params)
        el_value.append(
            py2xml(response)
        )

        return root

    @staticmethod
    def _parse_xml(xml_string):
        return etree.fromstring(xml_string, get_schema())

    @classmethod
    def _build_xml(cls, tree):
        return etree.tostring(
            tree,
            xml_declaration=True,
            encoding="utf-8",
            pretty_print=cls.DEBUG
        )

    def _get_exception_info(self, exc):
        return getattr(exc, 'code', -32500), repr(exc)

    def _format_exception(self, error):
        root = etree.Element('methodResponse')
        xml_fault = etree.Element('fault')
        xml_value = etree.Element('value')

        root.append(xml_fault)
        xml_fault.append(xml_value)

        code, exc_name = self._get_exception_info(error)

        xml_value.append(
            py2xml(
                OrderedDict((
                    ("faultCode", code),
                    ("faultString", exc_name),
                ))
            )
        )

        return root

    def _send_response(self, root):
        self.set_header("Content-Type", "text/xml; charset=utf-8")
        xml = self._build_xml(root)

        if self.DEBUG:
            log.debug("Sending response:\n%s", xml)

        self.finish(xml)

    @coroutine
    def post(self, *args, **kwargs):
        yield self._check_request()

        xml_request = yield self._parse_request()

        method_name = xml_request.xpath('//methodName[1]')[0].text
        method = yield self._resolve_method(method_name)

        log.info("RPC Call: %s => %s.%s.%s",
                 method_name,
                 method.__module__,
                 method.__class__.__name__,
                 method.__name__)

        args = list(map(
            xml2py,
            xml_request.xpath('//params/param/value/*')
        ))

        if args and isinstance(args[-1], dict):
            kwargs = args.pop(-1)
        else:
            kwargs = {}

        try:
            result = yield self._rpc_execute(method, *args, **kwargs)
            root = self._format_response(result)
        except Exception as e:
            log.exception('Error on %s', method_name)
            root = self._format_exception(e)

        self._send_response(root)
