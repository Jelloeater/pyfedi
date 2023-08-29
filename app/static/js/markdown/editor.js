// MIT license

var easyMarkdown = (function() {
    'use strict';
    var regexplink = new RegExp(
                      '^' +
                        // protocol identifier
                        '(?:(?:https?|ftp)://)' +
                        // user:pass authentication
                        '(?:\\S+(?::\\S*)?@)?' +
                        '(?:' +
                          // IP address exclusion
                          // private & local networks
                          '(?!(?:10|127)(?:\\.\\d{1,3}){3})' +
                          '(?!(?:169\\.254|192\\.168)(?:\\.\\d{1,3}){2})' +
                          '(?!172\\.(?:1[6-9]|2\\d|3[0-1])(?:\\.\\d{1,3}){2})' +
                          // IP address dotted notation octets
                          // excludes loopback network 0.0.0.0
                          // excludes reserved space >= 224.0.0.0
                          // excludes network & broacast addresses
                          // (first & last IP address of each class)
                          '(?:[1-9]\\d?|1\\d\\d|2[01]\\d|22[0-3])' +
                          '(?:\\.(?:1?\\d{1,2}|2[0-4]\\d|25[0-5])){2}' +
                          '(?:\\.(?:[1-9]\\d?|1\\d\\d|2[0-4]\\d|25[0-4]))' +
                        '|' +
                          // host name
                          '(?:(?:[a-z\\u00a1-\\uffff0-9]-*)*[a-z\\u00a1-\\uffff0-9]+)' +
                          // domain name
                          '(?:\\.(?:[a-z\\u00a1-\\uffff0-9]-*)*[a-z\\u00a1-\\uffff0-9]+)*' +
                          // TLD identifier
                          '(?:\\.(?:[a-z\\u00a1-\\uffff]{2,}))' +
                        ')' +
                        // port number
                        '(?::\\d{2,5})?' +
                        // resource path
                        '(?:/\\S*)?' +
                      '$', 'i'
                    );
    var regexppic = new RegExp(
                      '^' +
                        // protocol identifier
                        '(?:(?:https?|ftp)://)' +
                        // user:pass authentication
                        '(?:\\S+(?::\\S*)?@)?' +
                        '(?:' +
                          // IP address exclusion
                          // private & local networks
                          '(?!(?:10|127)(?:\\.\\d{1,3}){3})' +
                          '(?!(?:169\\.254|192\\.168)(?:\\.\\d{1,3}){2})' +
                          '(?!172\\.(?:1[6-9]|2\\d|3[0-1])(?:\\.\\d{1,3}){2})' +
                          // IP address dotted notation octets
                          // excludes loopback network 0.0.0.0
                          // excludes reserved space >= 224.0.0.0
                          // excludes network & broacast addresses
                          // (first & last IP address of each class)
                          '(?:[1-9]\\d?|1\\d\\d|2[01]\\d|22[0-3])' +
                          '(?:\\.(?:1?\\d{1,2}|2[0-4]\\d|25[0-5])){2}' +
                          '(?:\\.(?:[1-9]\\d?|1\\d\\d|2[0-4]\\d|25[0-4]))' +
                        '|' +
                          // host name
                          '(?:(?:[a-z\\u00a1-\\uffff0-9]-*)*[a-z\\u00a1-\\uffff0-9]+)' +
                          // domain name
                          '(?:\\.(?:[a-z\\u00a1-\\uffff0-9]-*)*[a-z\\u00a1-\\uffff0-9]+)*' +
                          // TLD identifier
                          '(?:\\.(?:[a-z\\u00a1-\\uffff]{2,}))' +
                        ')' +
                        // port number
                        '(?::\\d{2,5})?' +
                        // resource path
                        '(?:/\\S*)?' +
                        // image
                        '(?:jpg|gif|png)'+
                      '$', 'i'
                    );
    function createDom(obj){
        var nodeArray = [];
        for ( var i in obj){
            var node = document.createElement(obj[i].type);
            for ( var j in obj[i].attrs)
                node.setAttribute( j, obj[i].attrs[j]);
            if (obj[i].text)
                node.appendChild(document.createTextNode(obj[i].text));
            nodeArray[i] = node;
            if (typeof(obj[i].childrenOf) !== 'undefined')
                nodeArray[obj[i].childrenOf].appendChild(node);
        }
        return nodeArray[0];
    }
    function createNode(el,attrs,text){
        var node = document.createElement(el);
        for(var key in attrs)
            node.setAttribute(key, attrs[key]);
        if (text)
            node.appendChild(document.createTextNode(text));
        return node;
    }
    function applyStyle(el,attrs){
        for(var key in attrs)
            el.style[key] = attrs[key];
    }
    function merge(obj) {
        var i = 1,target, key;
        for (; i < arguments.length; i += 1) {
            target = arguments[i];
            for (key in target) 
                if (Object.prototype.hasOwnProperty.call(target, key)) 
                    obj[key] = target[key];
        }
        return obj;
    }
    function getStyle  (el,styleProp){
        var y;
        if (el.currentStyle)
            y = el.currentStyle[styleProp];
        else if (window.getComputedStyle)
            y = document.defaultView.getComputedStyle(el,null).getPropertyValue(styleProp);
        return y;
    }
    function easyMarkdown(node, options) {
        return new Editor(node, options);
    }
    /*==========  BUTTONS  ==========*/
    function Buttons(element,options,buttons) {
        this.element = element;
        this.options = options;
        this.locale = merge({}, easyMarkdown.locale, easyMarkdown.locale[options.locale] || {});
        this.buttons = {
            header: {
                title    : this.locale.header.title,
                text     : 'header',
                group    : 0,
                callback : function(e) {
                    // Append/remove ### surround the selection
                    var chunk, cursor, selected = e.getSelection(),
                        content = e.getContent();
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.header.description + '\n';
                    } else {
                        chunk = selected.text + '\n';
                    }
                    var key = 0,
                        hash='',
                        start = selected.start-1,
                        end = selected.start,
                        prevChr = content.substring(start,end); 
                    while (/^\s+$|^#+$/.test(prevChr)){
                        if (/^#+$/.test(prevChr))
                            hash = hash+'#';
                        key +=1;
                        prevChr = content.substring(start-key,end-key);
                    }

                    if (hash.length > 0){
                        // already a title
                        var startLinePos,
                            endLinePos = content.indexOf('\n', selected.start);
                    
                        //  more  than ### -> #
                        if (hash.length > 2){
                            hash = '#';
                            startLinePos = content.indexOf('\n', selected.start - 5);
                            e.setSelection(startLinePos, endLinePos+1);
                            e.replaceSelection('\n'+hash+' '+chunk);
                            cursor = startLinePos+3;
                        }else{
                            hash = hash +'#';
                            startLinePos = content.indexOf('\n', selected.start - (hash.length + 1));
                            e.setSelection(startLinePos, endLinePos+1);
                            e.replaceSelection('\n'+hash+' '+chunk);
                            cursor = selected.start + 1;
                        }
                    }else{

                        // new title
                        hash= '#';
                        e.replaceSelection('\n'+hash+' '+ chunk);
                        cursor = selected.start + 3;
                    }
                    e.setSelection(cursor, cursor + chunk.length-1);
                    return false;
                }
            },
            bold: {
                title    : this.locale.bold.title,
                text     : 'bold',
                group    : 0,
                callback : function(e) {
                    // Give/remove ** surround the selection
                    var chunk, cursor, selected = e.getSelection(),
                        content = e.getContent();
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.bold.description;
                    } else {
                        chunk = selected.text;
                    }
                    // transform selection and set the cursor into chunked text
                    if (content.substr(selected.start - 2, 2) === '**' && content.substr(selected.end, 2) === '**') {
                        e.setSelection(selected.start - 2, selected.end + 2);
                        e.replaceSelection(chunk);
                        cursor = selected.start - 2;
                    } else {
                        e.replaceSelection('**' + chunk + '**');
                        cursor = selected.start + 2;
                    }
                    // Set the cursor
                    e.setSelection(cursor, cursor + chunk.length);
                }
            },
            italic: {
                title    : this.locale.italic.title,
                text     : 'italic',
                group    : 0,
                callback : function(e) {
                    // Give/remove * surround the selection
                    var chunk, cursor, selected = e.getSelection(),
                        content = e.getContent();
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.italic.description;
                    } else {
                        chunk = selected.text;
                    }
                    // transform selection and set the cursor into chunked text
                    if (content.substr(selected.start - 1, 1) === '_' && content.substr(selected.end, 1) === '_') {
                        e.setSelection(selected.start - 1, selected.end + 1);
                        e.replaceSelection(chunk);
                        cursor = selected.start - 1;
                    } else {
                        e.replaceSelection('_' + chunk + '_');
                        cursor = selected.start + 1;
                    }
                    // Set the cursor
                    e.setSelection(cursor, cursor + chunk.length);
                }
            },
            image: {
                title    : this.locale.image.title,
                text     : 'image',
                group    : 1,
                callback : function(e) {
                    // Give ![] surround the selection and prepend the image link
                    var chunk, cursor, selected = e.getSelection(),
                        link;
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.image.description;
                    } else {
                        chunk = selected.text;
                    }
                    link = prompt(e.locale.image.title, 'http://');
                    if (regexppic.test(link)) {
                        e.replaceSelection('![' + chunk + '](' + link + ' "' + e.locale.image.description + '")');
                        cursor = selected.start + 2;
                        e.setSelection(cursor, cursor + chunk.length);
                    }
                    return false;
                }
            },
            link: {
                title    : this.locale.link.title,
                text     : 'link',
                group    : 1,
                callback : function(e) {
                    // Give [] surround the selection and prepend the link
                    var chunk, cursor, selected = e.getSelection(),
                        link;
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.link.description;
                    } else {
                        chunk = selected.text;
                    }
                    link = prompt(e.locale.link.title, 'http://');
                    if (regexplink.test(link)) {
                        e.replaceSelection('[' + chunk + '](' + link + ')');
                        cursor = selected.start + 1;
                        // Set the cursor
                        e.setSelection(cursor, cursor + chunk.length);
                    }
                    return false;
                }
            },
            ol: {
                title    : this.locale.ol.title,
                text     : 'ol',
                group    : 2,
                callback : function(e) {
                    // Prepend/Give - surround the selection
                    var chunk, cursor, selected = e.getSelection();
                    // transform selection and set the cursor into chunked text
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.ol.description;
                        e.replaceSelection('1. ' + chunk);
                        // Set the cursor
                        cursor = selected.start + 3;
                    } else {
                        if (selected.text.indexOf('\n') < 0) {
                            chunk = selected.text;
                            e.replaceSelection('1. ' + chunk);
                            // Set the cursor
                            cursor = selected.start + 3;
                        } else {
                            var list = [];
                            list = selected.text.split('\n');
                            chunk = list[0];
                            for (var key in list) {
                                var index = parseInt(key) + parseInt(1);
                                list[key] = index + '. ' + list[key];
                            }
                            e.replaceSelection('\n\n' + list.join('\n'));
                            // Set the cursor
                            cursor = selected.start + 5;
                        }
                    }
                    // Set the cursor
                    e.setSelection(cursor, cursor + chunk.length);
                }
            },
            ul: {
                title    : this.locale.ul.title,
                text     : 'ul',
                group    : 2,
                callback : function(e) {
                    // Prepend/Give - surround the selection
                    var chunk, cursor, selected = e.getSelection();
                    // transform selection and set the cursor into chunked text
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.ul.description;
                        e.replaceSelection('- ' + chunk);
                        // Set the cursor
                        cursor = selected.start + 2;
                    } else {
                        if (selected.text.indexOf('\n') < 0) {
                            chunk = selected.text;
                            e.replaceSelection('- ' + chunk);
                            // Set the cursor
                            cursor = selected.start + 2;
                        } else {
                            var list = [];
                            list = selected.text.split('\n');
                            chunk = list[0];
                            for (var key in list) {
                                list[key] = '- ' + list[key];
                            }
                            e.replaceSelection('\n\n' + list.join('\n'));
                            // Set the cursor
                            cursor = selected.start + 4;
                        }
                    }
                    // Set the cursor
                    e.setSelection(cursor, cursor + chunk.length);
                }
            },
            comment: {
                title    : this.locale.comment.title,
                text     : 'comment',
                group    : 3,
                callback : function(e) {
                    // Prepend/Give - surround the selection
                    var chunk, cursor, selected = e.getSelection(),
                        content = e.getContent();
                    // transform selection and set the cursor into chunked text
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.comment.description;
                        e.replaceSelection('> ' + chunk);
                        // Set the cursor
                        cursor = selected.start + 2;
                    } else {
                        if (selected.text.indexOf('\n') < 0) {
                            chunk = selected.text;
                            e.replaceSelection('> ' + chunk);
                            // Set the cursor
                            cursor = selected.start + 2;
                        } else {
                            var list = [];
                            list = selected.text.split('\n');
                            chunk = list[0];
                            for (var key in list)
                                list[key] = '> ' + list[key];
                            e.replaceSelection('\n\n' + list.join('\n'));
                            // Set the cursor
                            cursor = selected.start + 4;
                        }
                    }
                    // Set the cursor
                    e.setSelection(cursor, cursor + chunk.length);
                }
            },
            code: {
                title    : this.locale.code.title,
                text     : 'code',
                group    : 3,
                callback : function(e) {
                    // Give/remove ** surround the selection
                    var chunk, cursor, selected = e.getSelection(),
                        content = e.getContent();
                    if (selected.length === 0) {
                        // Give extra word
                        chunk = e.locale.code.description;
                    } else {
                        chunk = selected.text;
                    }
                    // transform selection and set the cursor into chunked text
                    if (content.substr(selected.start - 4, 4) === '```\n' && content.substr(selected.end, 4) === '\n```') {
                        e.setSelection(selected.start - 4, selected.end + 4);
                        e.replaceSelection(chunk);
                        cursor = selected.start - 4;
                    } else if (content.substr(selected.start - 1, 1) === '`' && content.substr(selected.end, 1) === '`') {
                        e.setSelection(selected.start - 1, selected.end + 1);
                        e.replaceSelection(chunk);
                        cursor = selected.start - 1;
                    } else if (content.indexOf('\n') > -1) {
                        e.replaceSelection('```\n' + chunk + '\n```');
                        cursor = selected.start + 4;
                    } else {
                        e.replaceSelection('`' + chunk + '`');
                        cursor = selected.start + 1;
                    }
                    // Set the cursor
                    e.setSelection(cursor, cursor + chunk.length);
                }
            },
            preview: {
                title    : this.locale.preview.title,
                text     : 'preview',
                group    : 4,
                callback : function(e) {
                        var txteditor = document.getElementById('easy-markdown');
                        var preview = document.getElementById('easy-preview');
                        var button = document.getElementById('easy-preview-close');
                        button.removeAttribute('disabled'); 
                        //preview.childNodes[1].childNodes[0].innerHTML = markdown.toHTML(e.element.value);
                        var md = window.markdownit();
                        
                        preview.childNodes[1].innerHTML = md.render(e.element.value);
                        txteditor.classList.add('is-hidden');                 
                        preview.classList.add('is-visible'); 
                }
            }
        };
        if (this.options.framework === 'bootstrap' || this.options.framework === 'foundation'){
            return this[this.options.framework]();
        }else{
            return this.none();
        }
    }
    Buttons.prototype = {
        getContent: function() {
            return this.element.value;
        },
        findSelection: function(chunk) {
            var content = this.getContent(),
                startChunkPosition;
            if (startChunkPosition = content.indexOf(chunk), startChunkPosition >= 0 && chunk.length > 0) {
                var oldSelection = this.getSelection(),
                    selection;
                this.setSelection(startChunkPosition, startChunkPosition + chunk.length);
                selection = this.getSelection();
                this.setSelection(oldSelection.start, oldSelection.end);
                return selection;
            } else {
                return null;
            }
        },
        getSelection: function() {
            var e = this.element;
            return (
                ('selectionStart' in e && function() {
                    var l = e.selectionEnd - e.selectionStart;
                    return {
                        start: e.selectionStart,
                        end: e.selectionEnd,
                        length: l,
                        text: e.value.substr(e.selectionStart, l)
                    };
                }) ||
                /* browser not supported */
                function() {
                    return null;
                }
            )();
        },
        setIcons: function(element,button){
            if (typeof(this.options.icons) === 'string'){
                var t = document.createTextNode(element.title);
                button.appendChild(t);
               
            }else{
                var i = document.createElement('I');
                i.setAttribute('class', this.options.icons[element.text]);
                button.appendChild(i);
            }
        },
        setListener: function(node) {
            var that = this;
            node.addEventListener('click', function(e) {
                var element = e.target,
                    target = (element.nodeName === 'I') ? element.parentNode : element;
                that.buttons[target.getAttribute('data-md')].callback(that);
                e.preventDefault();
            }, false);
            return node;
        },
        setSelection: function(start, end) {
            var e = this.element;
            return (
                ('selectionStart' in e && function() {
                    e.selectionStart = start;
                    e.selectionEnd = end;
                    return;
                }) ||
                /* browser not supported */
                function() {
                    return null;
                }
            )();
        },
        replaceSelection: function(text) {
            var e = this.element;
            return (
                ('selectionStart' in e && function() {
                    e.value = e.value.substr(0, e.selectionStart) + text + e.value.substr(e.selectionEnd, e.value.length);
                    // Set cursor to the last replacement end
                    e.selectionStart = e.value.length;
                    return this;
                })
            )();
        }
    };
    Buttons.prototype.bootstrap = function(){
        var button_groups =  createDom ({
                0 : {'type':'div'},
                1 : {'type':'div','attrs': {'class':'btn-group','role':'group','style':'margin:5px;'},'childrenOf': 0},
                2 : {'type':'div','attrs': {'class':'btn-group','role':'group','style':'margin:5px;'},'childrenOf': 0},
                3 : {'type':'div','attrs': {'class':'btn-group','role':'group','style':'margin:5px;'},'childrenOf': 0},
                4 : {'type':'div','attrs': {'class':'btn-group','role':'group','style':'margin:5px;'},'childrenOf': 0},
                5 : {'type':'div','attrs': {'class':'btn-group','role':'group','style':'margin:5px;'},'childrenOf': 0}
            });
        for (var i in this.buttons) {
            var obj = this.buttons[i];
            if (this.options.disabled[obj.text] !== true) {
                var button = createNode('BUTTON',{'class':this.options.btnClass,'data-md':obj.text,'title':obj.title });
                this.setIcons(obj,button);
                button_groups.childNodes[obj.group].appendChild(button);
            }
        }
        this.setListener(button_groups);
        return button_groups;
    };
    Buttons.prototype.foundation = function(){
        var container = createNode('UL',{'class': 'button-group','style':'margin: 0 0 10px 0;'});
            for (var i in this.buttons) {
                var obj = this.buttons[i];
                if (this.options.disabled[obj.text] !== true) {
                    var li = createNode('LI');
                    var a = createNode('A',{'class':this.options.btnClass,'data-md':obj.text,'title':obj.title });
                    this.setIcons(obj,a);
                    container.appendChild(li).appendChild(a);
                }
            }
        this.setListener(container);
        return container;
    };
    Buttons.prototype.none = function(){
        var container = document.createElement('DIV');
        for (var key in this.buttons) {
            var obj = this.buttons[key];
            if (this.options.disabled[obj.text] !== true) { 
                var button = createNode('BUTTON',{'class':this.options.btnClass,'data-md':obj.text,'title':obj.title });
                this.setIcons(obj,button);
                container.appendChild(button);
            }
        }
        this.setListener(container);
        return container;
    };
    /*==========  SKELETON  ==========*/
     
    function Skeleton(options,textarea,buttons) {
        this.element = textarea;
        this.options =  options;
        this.buttons = buttons;
        return this.build();
    }
    Skeleton.prototype = {
        build : function(){
            var buttons = new Buttons(this.element,this.options,this.buttons);
            var dom = createDom ({
                    0 : {'type':'div','attrs': {'class':'easy-markdown','id':'easy-markdown'}},
                    1 : {'type':'div','attrs': {'id':'easy-markdown-buttons'},'childrenOf': 0},
                    2 : {'type':'div','attrs': {'id':'easy-markdown-textarea'},'childrenOf': 0}
                });
            dom.childNodes[0].appendChild(buttons);
            dom.childNodes[1].appendChild(this.element);
            return dom;
        }
    };
    /*==========  PREVIEW  ==========*/
    function Preview(options,parent) {
        this.parent = parent;
        this.options =  options;
        this.locale = merge({}, easyMarkdown.locale, easyMarkdown.locale[options.locale] || {});
        return this.build();
    }
    Preview.prototype = {
        build: function() {
            
            var dom = createDom ({
                0 : {'type':'div','attrs': {'class':'easy-preview','id':'easy-preview','style':'height:'+this.parent.clientHeight +'px;'}},
                1 : {'type':'div','attrs': {'id':'easy-preview-buttons'},'childrenOf': 0},
                2 : {'type':'div','attrs': {'id':'easy-preview-html','style':'overflow:auto;'},'childrenOf': 0},
                3 : {'type':'button','attrs':{'class':this.options.btnClass,'disabled':'disabled','id':'easy-preview-close'},'text':this.locale.getback.title,'childrenOf': 1},
                4 : {'type':'HR','childrenOf':1}
            });
            this.setListener(dom.childNodes[0].childNodes[0]);
            this.parent.appendChild(dom);
            dom.childNodes[1].style.height = this.parent.clientHeight - dom.childNodes[0].clientHeight - 20 +'px';
            
        },
        setListener : function(node){
            node.addEventListener('click', function(e) {
                var txteditor = document.getElementById('easy-markdown');
                var preview = document.getElementById('easy-preview');
                var button = document.getElementById('easy-preview-close');
                button.setAttribute('disabled','disabled');
                txteditor.classList.remove('is-hidden');
                preview.classList.remove('is-visible');
                e.preventDefault();
            }, false);
            return node;
        }
    };
    /*==========  EDITOR  ==========*/
    function Editor(node, options) {
        this.element = node;
        this.parent = node.parentNode;
        this.parent.innerHTML = '';
        this.options = merge({}, Editor.defaults, options || {});
        // test if markdown.js is missing
        if (typeof(markdownit) === 'undefined')
            this.options.disabled.preview = true;
        this.preview = 'off';
        var skeleton = new Skeleton(this.options,this.element);
        node.style.width = this.options.width;
        this.parent.appendChild(skeleton);

        applyStyle(this.parent,{position:'relative',height:skeleton.clientHeight+'px',overflow:'hidden'});
        new Preview(this.options,this.parent);
    }
    easyMarkdown.Preview = Preview;
    easyMarkdown.Buttons = Buttons;
    easyMarkdown.Skeleton = Skeleton;
    easyMarkdown.Editor = Editor;
    easyMarkdown.locale = {
        bold: {
          title:'Bold',
          description:'Strong Text'   
        },
        italic: {
          title:'Italic' ,
          description: 'Emphasized text' 
        },
        header: {
          title:'Header',
          description: 'Heading text' 
        },
        image: {
          title:'Image',
          description:'Image description'  
        },
        link: {
          title:'Link',
          description:'Link description'
        },
        ol: {
          title:'Numbered',
          description:'Numbered list' 
        },
        ul: {
          title:'Bullet',
          description:'Bulleted list'  
        },
        comment: {
          title:'Comment',
          description: 'Comment'  
        },
        code: {
          title:'Code',
          description: 'code text' 
        },
        preview: {
          title:'Preview'   
        },
        getback: {
            title: 'Get back'
        }
    };
    Editor.defaults = {
        width: '100%',
        btnClass: '',
        framework: 'none',
        locale:'',
        icons: '',
        disabled: {
            bold: false,
            italic: false,
            header: false,
            image: false,
            link: false,
            ol: false,
            ul: false,
            comment: false,
            code: false,
            preview: false
        }
    };

    return easyMarkdown;

})();
