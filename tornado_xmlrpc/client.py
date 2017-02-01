# encoding: utf-8
from lxml import etree
from tornado.gen import coroutine, Return
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.ioloop import IOLoop

from . import __version__, __pyversion__
from .common import py2xml, xml2py, get_schema


class XMLRPCClientException(Exception):
    pass


class InvalidResponse(XMLRPCClientException):
    pass


class RemoteServerException(XMLRPCClientException):
    def __init__(self, message, code=-32500):
        Exception.__init__(self, message)
        self.code = code


class RemoteMethod(object):
    __slots__ = '__name', '__handler'

    def __init__(self, method_name, handler):
        self.__name = method_name
        self.__handler = handler

    def __call__(self, *args, **kwargs):
        return self.__handler._remote_call(
            self.__name, *args, **kwargs
        )

    def __getattr__(self, method_name):
        return RemoteMethod(
            '{}.{}'.format(self.__name, method_name),
            self.__handler
        )

    def __repr__(self):
        return "<RemoteMethod: {0}>".format(self.__name)


class ServerProxy(object):
    USER_AGENT = u'Tornado XML-RPC (Python: {0}, version: {1})'.format(__pyversion__, __version__)

    def __init__(self, url, http_client=None, http_params=None):
        self.url = str(url)
        self.client = http_client or AsyncHTTPClient(IOLoop.current())
        self._http_params = http_params or {}

    @staticmethod
    def _make_request(method_name, *args, **kwargs):
        root = etree.Element('methodCall')
        method_el = etree.Element('methodName')
        method_el.text = method_name

        root.append(method_el)

        params_el = etree.Element('params')
        root.append(params_el)

        for arg in args:
            param = etree.Element('param')
            val = etree.Element('value')
            param.append(val)
            params_el.append(param)
            val.append(py2xml(arg))

        if kwargs:
            param = etree.Element('param')
            val = etree.Element('value')
            param.append(val)
            params_el.append(param)
            val.append(py2xml(kwargs))

        return root

    @staticmethod
    def _parse_response(body, method_name):
        try:
            response = etree.fromstring(body, get_schema())
        except etree.XMLSyntaxError as e:
            raise ValueError("Invalid body")

        result = response.xpath('//params/param/value/*')
        if result:
            return xml2py(result[0])

        fault = response.xpath('//fault/value/*')
        if fault:
            err = xml2py(fault[0])
            raise RemoteServerException(err.get('faultString'), err.get('faultCode'))

        raise InvalidResponse('Respond body of method "%s" not contains any response.', method_name)

    @coroutine
    def _remote_call(self, method_name, *args, **kwargs):
        req = HTTPRequest(
            str(self.url),
            method='POST',
            body=etree.tostring(self._make_request(method_name, *args, **kwargs), xml_declaration=True),
            headers={
                'Content-Type': u'text/xml',
                'User-Agent': self.USER_AGENT
            }, **self._http_params
        )
        response = yield self.client.fetch(req)

        raise Return(self._parse_response(response.body, method_name))

    def __getattr__(self, method_name):
        return RemoteMethod(method_name, self)
